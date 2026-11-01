"""Optional headphone monitor output for the native pipeline."""
from __future__ import annotations

import queue
import threading
import time

import numpy as np


def resolve_monitor_device(sd) -> tuple[int, str]:
    devices = sd.query_devices()
    default = sd.default.device[1]
    candidates = []
    for i, d in enumerate(devices):
        name = str(d["name"])
        if int(d["max_output_channels"]) < 2:
            continue
        if "CABLE" in name.upper():
            continue
        api = str(sd.query_hostapis(int(d["hostapi"]))["name"])
        score = 0
        if i == default:
            score += 3
        if "WASAPI" in api:
            score += 4
        if abs(float(d["default_samplerate"]) - 48000.0) < 1:
            score += 1
        candidates.append((score, i, name, api))
    if not candidates:
        raise RuntimeError("找不到耳机/扬声器输出设备。")
    candidates.sort(reverse=True)
    _, idx, name, api = candidates[0]
    return idx, f"{name} [{api}]"


class MonitorOutput:
    """Same jitter-buffered writer as CableOutput, targeting headphones."""

    def __init__(self, gain: float = 2.0, blocksize: int = 960,
                 prebuffer: int = 1, max_queue: int = 4):
        self.gain = float(gain)
        self.blocksize = int(blocksize)
        self.prebuffer = max(1, int(prebuffer))
        self.max_queue = int(max_queue)
        self.samplerate = 48000
        self.active = False
        self.device = None
        self.error = None
        self.dropped = 0
        self.underruns = 0
        self._queue = None
        self._stream = None
        self._thread = None
        self._stop = threading.Event()

    def start(self) -> dict:
        self.stop()
        import sounddevice as sd
        idx, name = resolve_monitor_device(sd)
        self._queue = queue.Queue(maxsize=self.max_queue)
        self._stop.clear()
        self._stream = sd.OutputStream(
            device=idx, samplerate=self.samplerate, channels=2,
            dtype="float32", blocksize=self.blocksize, latency="low",
        )
        self._stream.start()
        self.device = name
        self.active = True
        self.error = None
        self.dropped = 0
        self.underruns = 0
        self._thread = threading.Thread(target=self._writer, daemon=True, name="monitor-output")
        self._thread.start()
        return self.status()

    def push(self, chunk: np.ndarray) -> None:
        if not self.active or self._queue is None:
            return
        x = np.asarray(chunk, dtype=np.float32).reshape(-1).copy()
        if x.size == 0:
            return
        try:
            self._queue.put_nowait(x)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self.dropped += 1
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(x)
            except queue.Full:
                self.dropped += 1

    def _writer(self) -> None:
        import soxr
        silence = np.zeros((self.blocksize, 2), np.float32)
        while not self._stop.is_set() and self._queue.qsize() < self.prebuffer:
            time.sleep(0.01)
        while not self._stop.is_set():
            try:
                chunk = self._queue.get(timeout=0.05)
            except queue.Empty:
                try:
                    if self._stream is None:
                        break
                    self._stream.write(silence)
                    self.underruns += 1
                except Exception as exc:
                    if not self._stop.is_set():
                        self.error = str(exc)
                    break
                continue
            try:
                y = soxr.resample(chunk, 16000, self.samplerate, quality="HQ")
                y = np.clip(y * self.gain, -1.0, 1.0).astype(np.float32)
                stereo = np.stack([y, y], axis=1)
                for i in range(0, len(stereo), self.blocksize):
                    block = stereo[i:i + self.blocksize]
                    if len(block) < self.blocksize:
                        block = np.pad(block, ((0, self.blocksize - len(block)), (0, 0)))
                    self._stream.write(block)
            except Exception as exc:
                if not self._stop.is_set():
                    self.error = str(exc)
                break

    def stop(self) -> None:
        self._stop.set()
        self.active = False
        stream, thread = self._stream, self._thread
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.5)
        self._stream = self._thread = None
        self._queue = None

    def status(self) -> dict:
        return {
            "active": self.active, "device": self.device, "error": self.error,
            "queued": self._queue.qsize() if self._queue is not None else 0,
            "dropped": self.dropped, "underruns": self.underruns,
            "gain_db": float(round(20 * np.log10(self.gain + 1e-12), 1)),
        }
