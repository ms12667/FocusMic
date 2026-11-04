"""Windowed Falcon inference loop for the native app."""
from __future__ import annotations

import time
from collections import deque
from pathlib import Path

import numpy as np

from .monitor import MonitorOutput
from .output import CableOutput
from .paths import weight_path

# Must match falcon_runtime.WINDOW_SAMPLES.  Kept local so importing this
# module does not import torch (the runtime is supplied by a separate package).
WINDOW_SAMPLES = 32_000
WINDOW = WINDOW_SAMPLES
FPS = 25
GUARD = 1280
FRAME = 640
FADE = 320


class NativePipeline:
    def __init__(self, audio, mouth, *, variant="small", av_offset_ms=30.0,
                 hop=3200, gain_db=6.0, output=True, monitor=False, safe_mode=True,
                 save_wav=None, log=None):
        self.audio = audio
        self.mouth = mouth
        self.log = log or (lambda text: print(text, flush=True))
        self.variant = variant
        self.av_offset_ms = float(av_offset_ms)
        self.hop = int(hop)
        self.gain = float(10 ** (gain_db / 20.0))
        self.output = CableOutput(gain=1.0, blocksize=960, prebuffer=1, max_queue=4) if output else None
        self.monitor = MonitorOutput(gain=1.0, blocksize=960, prebuffer=1, max_queue=4) if monitor else None
        self.monitor_error = None
        self.save_wav = Path(save_wav) if save_wav else None
        self.runtime = None
        self.saved = []
        self.running = False
        self.cancel = False
        self.error = None
        self.windows = 0
        self.skipped = 0
        self.last_infer_ms = 0.0
        self.max_infer_ms = 0.0
        self.last_tracked = 0.0
        self.last_lag = 0.0
        self.last_full_latency = 0.0
        self._queue_ema = 0.0
        self.safe_mode = bool(safe_mode)
        self.bypass = False
        self.manual_bypass = False
        self.last_effective_bypass = False
        self.ever_tracked = False
        self.warmup_windows = 10
        self.bypass_count = 0
        self.manual_bypass_count = 0
        self._last_manual = False
        self.session_started = None
        self.last_elapsed = 0.0
        self.history = deque(maxlen=60)          # 12 s of (raw, out) chunks
        self.suppression_history = deque(maxlen=40)

    def load(self, device="cuda"):
        from .runtime import ensure_runtime

        status = ensure_runtime(check_cuda=device == "cuda")
        if not status.ok:
            raise RuntimeError(status.message())
        # Imported only after the external runtime is on sys.path.
        from .vendor.falcon.falcon_runtime import FalconRuntime

        weights = weight_path(self.variant)
        self.runtime = FalconRuntime(self.variant, str(weights)).load(device)
        return self

    def run(self, duration: float | None = None):
        if self.cancel:
            return
        if self.runtime is None:
            self.load()
        if self.cancel:
            return
        try:
            self.audio.start()
            self.mouth.start()
            # Align the file-backed video timeline with the audio clock.
            if hasattr(self.mouth, "align_to"):
                self.mouth.align_to(self.audio.start_time)
            if self.output is not None:
                self.output.start()
        except Exception:
            if self.output is not None:
                self.output.stop()
            self.mouth.stop()
            self.audio.stop()
            raise
        if self.monitor is not None:
            try:
                self.monitor.start()
            except Exception as exc:
                self.monitor_error = str(exc)
                self.log(f"耳机监听不可用，继续分离：{exc}")
                try:
                    self.monitor.stop()
                except Exception:
                    pass
                self.monitor = None
        if self.cancel:
            if self.output is not None:
                self.output.stop()
            if self.monitor is not None:
                self.monitor.stop()
            self.mouth.stop()
            self.audio.stop()
            return
        self.running = True
        session_epoch = int(self.audio.total)
        end = session_epoch + self.hop + GUARD
        future = None
        last_end = None
        last_output_tail = None
        lost_windows = 0
        ok_windows = 0
        last_report = time.perf_counter()
        started = time.perf_counter()
        self.session_started = started
        try:
            while self.running:
                if duration is not None and time.perf_counter() - started >= duration:
                    break
                # Wait for enough audio, but do not fall behind: if the model
                # cannot keep up, jump to the newest hop and drop stale windows.
                last_total = self.audio.total
                last_progress = time.perf_counter()
                while self.running and self.audio.total < end:
                    if duration is not None and time.perf_counter() - started >= duration:
                        break
                    now = time.perf_counter()
                    if self.audio.total != last_total:
                        last_total = self.audio.total
                        last_progress = now
                    elif now - last_progress > 1.5:
                        raise RuntimeError(
                            "麦克风没有音频数据（设备可能已断开）。")
                    time.sleep(0.005)
                if not self.running:
                    break
                if duration is not None and time.perf_counter() - started >= duration:
                    break
                latest = session_epoch + GUARD + ((self.audio.total - session_epoch - GUARD) // self.hop) * self.hop
                if latest - end > self.hop * 2:
                    self.skipped += int((latest - end) // self.hop)
                    end = latest
                    future = None
                    last_end = None
                start = end - WINDOW
                window = self.audio.read(start, end)
                zero_before = max(0, session_epoch - start)
                if zero_before:
                    window[:min(zero_before, len(window))] = 0.0
                t0 = self.audio.time_at(start)
                t1 = self.audio.time_at(end)
                frames, tracked = self.mouth.frames_for(t0, t1, 50, self.av_offset_ms)
                self.last_tracked = tracked
                begin = time.perf_counter()
                pred = self.runtime.infer(np.ascontiguousarray(window, dtype=np.float32),
                                          np.ascontiguousarray(frames, dtype=np.uint8))
                self.last_infer_ms = (time.perf_counter() - begin) * 1000.0
                self.max_infer_ms = max(self.max_infer_ms, self.last_infer_ms)
                stop = WINDOW - GUARD
                chunk = pred[stop - self.hop:stop].copy()
                if future is not None and last_end is not None and end - last_end == self.hop:
                    ramp = np.linspace(0, 1, FADE, dtype=np.float32)
                    chunk[:FADE] = future * (1 - ramp) + chunk[:FADE] * ramp
                model_future = pred[stop:stop + FADE].copy()
                last_end = end
                raw = window[stop - self.hop:stop].copy()
                mode_changed = False
                manual_pending = False
                if hasattr(self.mouth, "status"):
                    try:
                        manual_pending = bool(self.mouth.status().get("manual_pick"))
                    except Exception:
                        manual_pending = False
                if self.safe_mode:
                    if tracked >= 0.4:
                        self.ever_tracked = True
                    if manual_pending:
                        lost_windows = 0
                        ok_windows = 0
                    elif self.windows < self.warmup_windows:
                        # Camera/MediaPipe warm-up: do not count the first
                        # ~2 s as visual loss or every start bypasses once.
                        lost_windows = 0
                        ok_windows = 1 if tracked >= 0.4 else 0
                    elif not self.ever_tracked and self.windows < self.warmup_windows * 2:
                        # Still waiting for the first successful face lock.
                        lost_windows = 0
                        ok_windows = 0
                    elif tracked < 0.4:
                        lost_windows += 1
                        ok_windows = 0
                    else:
                        lost_windows = 0
                        ok_windows += 1
                    if not self.bypass and lost_windows >= 3:
                        self.bypass = True
                        self.bypass_count += 1
                        mode_changed = True
                        print("视觉丢失：直通原始麦克风", flush=True)
                    elif self.bypass and ok_windows >= 2:
                        self.bypass = False
                        mode_changed = True
                        print("视觉恢复：回到分离输出", flush=True)
                if self.manual_bypass and not self._last_manual:
                    self.manual_bypass_count += 1
                self._last_manual = self.manual_bypass
                effective_bypass = self.bypass or self.manual_bypass
                if effective_bypass != self.last_effective_bypass:
                    mode_changed = True
                    self.last_effective_bypass = effective_bypass
                if effective_bypass:
                    out_chunk = raw
                    future = None
                else:
                    out_chunk = chunk
                    future = model_future
                if mode_changed and last_output_tail is not None:
                    ramp = np.linspace(0, 1, FADE, dtype=np.float32)
                    out_chunk[:FADE] = last_output_tail * (1 - ramp) + out_chunk[:FADE] * ramp
                last_output_tail = out_chunk[-FADE:].copy()
                play_chunk = out_chunk if effective_bypass else out_chunk * self.gain
                if self.output is not None:
                    self.output.push(play_chunk)
                if self.monitor is not None:
                    self.monitor.push(play_chunk)
                if self.save_wav is not None:
                    self.saved.append(out_chunk.copy())
                if not effective_bypass:
                    raw_rms = float(np.sqrt(np.mean(np.square(raw, dtype=np.float64))))
                    out_rms = float(np.sqrt(np.mean(np.square(out_chunk, dtype=np.float64))))
                    if raw_rms > 1e-4:
                        db = 30.0 if out_rms <= 1e-6 else 20.0 * np.log10(raw_rms / out_rms)
                        self.suppression_history.append(float(np.clip(db, -30.0, 30.0)))
                self.history.append((raw.copy(), out_chunk.copy(), bool(effective_bypass)))
                queued = 0
                device_latency = 0.0
                if self.output is not None:
                    out_status = self.output.status()
                    queued = int(out_status.get("queued", 0))
                    device_latency = float(out_status.get("latency", 0.0))
                elif self.monitor is not None:
                    mon_status = self.monitor.status()
                    queued = int(mon_status.get("queued", 0))
                    device_latency = float(mon_status.get("latency", 0.0))
                buffered = max(0, self.audio.total - (end - GUARD)) / 16000.0
                self._queue_ema = 0.8 * self._queue_ema + 0.2 * queued
                input_latency = float(getattr(self.audio, "latency", 0.0) or 0.0)
                self.last_full_latency = (
                    input_latency + buffered
                    + self._queue_ema * self.hop / 16000.0 + device_latency)
                self.windows += 1
                # Console stats once per second.
                now = time.perf_counter()
                if now - last_report >= 1.0:
                    last_report = now
                    lag = (self.audio.total - end) / 16000.0
                    self.last_lag = lag
                    out = self.output.status() if self.output is not None else {"active": False}
                    self.log(
                        f"推理 {self.last_infer_ms:5.1f} ms · 全链路 "
                        f"{self.last_full_latency:4.2f} s · 窗口 {self.windows} · "
                        f"跳过 {self.skipped} · "
                        f"跟踪 {tracked*100:5.1f}% · CABLE "
                        f"{out.get('queued',0)}q/{out.get('dropped',0)}drop"
                        f"{' · 直通' if (self.bypass or self.manual_bypass) else ''}")
                end += self.hop
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            if self.session_started is not None:
                self.last_elapsed = time.perf_counter() - self.session_started
            if self.output is not None:
                self.output.stop()
            if self.monitor is not None:
                self.monitor.stop()
            self.mouth.stop()
            self.audio.stop()
            if self.save_wav is not None and self.saved:
                import soundfile as sf
                y = np.concatenate(self.saved)
                sf.write(str(self.save_wav), y, 16000, subtype="PCM_16")
                print(f"saved {self.save_wav} ({len(y)/16000:.1f}s)", flush=True)

    def _suppression_db(self) -> float:
        values = list(self.suppression_history)
        return float(sum(values) / len(values)) if values else 0.0

    def _elapsed(self) -> float:
        if self.session_started is None:
            return 0.0
        if self.running:
            return time.perf_counter() - self.session_started
        return self.last_elapsed

    def status(self) -> dict:
        cable = self.output.status() if self.output is not None else {"active": False}
        monitor = self.monitor.status() if self.monitor is not None else {"active": False}
        return {
            "running": self.running,
            "windows": self.windows,
            "skipped": self.skipped,
            "infer_ms": self.last_infer_ms,
            "max_infer_ms": self.max_infer_ms,
            "tracked": self.last_tracked,
            "audio_lag": self.last_lag,
            "full_latency": self.last_full_latency,
            "suppression_db": self._suppression_db(),
            "bypass_count": self.bypass_count,
            "manual_bypass_count": self.manual_bypass_count,
            "elapsed": self._elapsed(),
            "bypass": self.bypass or self.manual_bypass,
            "safe_bypass": self.bypass,
            "manual_bypass": self.manual_bypass,
            "cable": cable,
            "monitor": monitor,
        }

    def report(self, seconds: float = 8.0) -> dict:
        """Recent raw/output audio plus session counters for the report page."""
        count = max(1, int(seconds * 16000 / self.hop))
        chunks = list(self.history)[-count:]
        if chunks:
            raw = np.concatenate([c[0] for c in chunks])
            out = np.concatenate([c[1] for c in chunks])
            bypass = [bool(c[2]) for c in chunks]
        else:
            raw = np.zeros(0, np.float32)
            out = np.zeros(0, np.float32)
            bypass = []
        return {
            "sample_rate": 16000,
            "raw": raw,
            "out": out,
            "bypass": bypass,
            "suppression_db": self._suppression_db(),
            "suppression_samples": len(self.suppression_history),
            "bypass_count": self.bypass_count,
            "manual_bypass_count": self.manual_bypass_count,
            "max_infer_ms": self.max_infer_ms,
            "infer_ms": self.last_infer_ms,
            "full_latency": self.last_full_latency,
            "tracked": self.last_tracked,
            "windows": self.windows,
            "skipped": self.skipped,
            "elapsed": self._elapsed(),
            "cable": self.output.status() if self.output is not None else {"active": False},
            "gain_db": float(round(20 * np.log10(self.gain + 1e-12), 1)),
        }

    def stop(self):
        self.cancel = True
        self.running = False
