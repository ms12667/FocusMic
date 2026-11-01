"""Windowed Falcon inference loop for the native app."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

PROBE = Path(__file__).resolve().parents[1]
STUDIO = PROBE / "Falcon" / "studio"
if str(STUDIO) not in sys.path:
    sys.path.insert(0, str(STUDIO))

from falcon_runtime import FalconRuntime, WINDOW_SAMPLES  # noqa: E402
from native_output import CableOutput  # noqa: E402

WINDOW = WINDOW_SAMPLES
FPS = 25
GUARD = 1280
FRAME = 640
FADE = 320


class NativePipeline:
    def __init__(self, audio, mouth, *, variant="small", av_offset_ms=30.0,
                 hop=3200, gain_db=6.0, output=True, save_wav=None):
        self.audio = audio
        self.mouth = mouth
        self.variant = variant
        self.av_offset_ms = float(av_offset_ms)
        self.hop = int(hop)
        self.gain = float(10 ** (gain_db / 20.0))
        self.output = CableOutput(gain=self.gain, blocksize=960, prebuffer=1, max_queue=4) if output else None
        self.save_wav = Path(save_wav) if save_wav else None
        self.runtime = None
        self.saved = []
        self.running = False
        self.error = None
        self.windows = 0
        self.skipped = 0
        self.last_infer_ms = 0.0

    def load(self, device="cuda"):
        weights = PROBE / "weights" / ("falcon-big.pt" if self.variant == "big" else "falcon.pt")
        self.runtime = FalconRuntime(self.variant, str(weights)).load(device)
        return self

    def run(self, duration: float | None = None):
        if self.runtime is None:
            self.load()
        self.audio.start()
        self.mouth.start()
        # Align the file-backed video timeline with the audio clock.
        if hasattr(self.mouth, "align_to"):
            self.mouth.align_to(self.audio.start_time)
        if self.output is not None:
            self.output.start()
        self.running = True
        session_epoch = int(self.audio.total)
        end = session_epoch + self.hop + GUARD
        future = None
        last_end = None
        last_report = time.perf_counter()
        started = time.perf_counter()
        try:
            while self.running:
                if duration is not None and time.perf_counter() - started >= duration:
                    break
                # Wait for enough audio, but do not fall behind: if the model
                # cannot keep up, jump to the newest hop and drop stale windows.
                while self.audio.total < end:
                    if duration is not None and time.perf_counter() - started >= duration:
                        break
                    time.sleep(0.005)
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
                begin = time.perf_counter()
                pred = self.runtime.infer(np.ascontiguousarray(window, dtype=np.float32),
                                          np.ascontiguousarray(frames, dtype=np.uint8))
                self.last_infer_ms = (time.perf_counter() - begin) * 1000.0
                stop = WINDOW - GUARD
                chunk = pred[stop - self.hop:stop].copy()
                if future is not None and last_end is not None and end - last_end == self.hop:
                    ramp = np.linspace(0, 1, FADE, dtype=np.float32)
                    chunk[:FADE] = future * (1 - ramp) + chunk[:FADE] * ramp
                future = pred[stop:stop + FADE].copy()
                last_end = end
                if self.output is not None:
                    self.output.push(chunk)
                if self.save_wav is not None:
                    self.saved.append(chunk.copy())
                self.windows += 1
                # Console stats once per second.
                now = time.perf_counter()
                if now - last_report >= 1.0:
                    last_report = now
                    lag = (self.audio.total - end) / 16000.0
                    out = self.output.status() if self.output is not None else {"active": False}
                    print(f"infer {self.last_infer_ms:5.1f} ms | windows {self.windows} | "
                          f"skip {self.skipped} | audio lag {lag:5.2f}s | "
                          f"tracked {tracked*100:5.1f}% | cable {out.get('queued',0)}q/"
                          f"{out.get('dropped',0)}drop", flush=True)
                end += self.hop
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            if self.output is not None:
                self.output.stop()
            self.mouth.stop()
            self.audio.stop()
            if self.save_wav is not None and self.saved:
                import soundfile as sf
                y = np.concatenate(self.saved)
                sf.write(str(self.save_wav), y, 16000, subtype="PCM_16")
                print(f"saved {self.save_wav} ({len(y)/16000:.1f}s)", flush=True)

    def stop(self):
        self.running = False
