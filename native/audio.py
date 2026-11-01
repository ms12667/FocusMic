"""Audio input sources for the native FocusMic pipeline."""
from __future__ import annotations

import threading
import time
from collections import deque
from pathlib import Path

import numpy as np


def list_input_devices(sd) -> list[dict]:
    out = []
    for i, d in enumerate(sd.query_devices()):
        if int(d["max_input_channels"]) < 1:
            continue
        api = sd.query_hostapis(int(d["hostapi"]))["name"]
        out.append({
            "index": i,
            "name": str(d["name"]),
            "channels": int(d["max_input_channels"]),
            "samplerate": float(d["default_samplerate"]),
            "hostapi": str(api),
        })
    return out


def resolve_input(sd, spec: str | int | None) -> tuple[int, dict]:
    devices = list_input_devices(sd)
    if not devices:
        raise RuntimeError("没有可用的录音设备。")
    if spec is None or spec == "":
        wanted = sd.default.device[0]
        for d in devices:
            if d["index"] == wanted:
                return d["index"], d
        return devices[0]["index"], devices[0]
    if isinstance(spec, int) or str(spec).isdigit():
        idx = int(spec)
        for d in devices:
            if d["index"] == idx:
                return idx, d
        raise RuntimeError(f"找不到录音设备索引 {idx}。")
    needle = str(spec).lower()
    matches = [d for d in devices if needle in d["name"].lower()]
    if not matches:
        raise RuntimeError(f"找不到名称包含 {spec!r} 的录音设备。")
    # Prefer WASAPI, then a non-virtual physical device.
    matches.sort(key=lambda d: (
        "WASAPI" not in d["hostapi"],
        "CABLE" in d["name"].upper() or "STEAM" in d["name"].upper(),
        d["index"],
    ))
    d = matches[0]
    return d["index"], d


class LiveAudio:
    """WASAPI/PortAudio capture, resampled to 16 kHz, with a 20 s ring."""

    def __init__(self, device: str | int | None = None, ring_seconds: float = 20.0,
                 target_rate: int = 16000):
        import sounddevice as sd
        self._sd = sd
        self.index, self.info = resolve_input(sd, device)
        self.target_rate = target_rate
        self.input_rate = int(round(self.info["samplerate"])) or 48000
        self.ring = np.zeros(int(target_rate * ring_seconds), np.float32)
        self._lock = threading.Lock()
        self.total = 0
        self.start_time = None
        self.stream = None
        self.error = None
        self._resampler = None
        self._channels = 1

    def start(self):
        import soxr
        self._resampler = soxr.ResampleStream(self.input_rate, self.target_rate, 1, dtype="float32")
        self.start_time = time.perf_counter()
        # Try mono; some devices only expose stereo.
        for channels in (1, 2):
            try:
                self.stream = self._sd.InputStream(
                    device=self.index, samplerate=self.input_rate, channels=channels,
                    dtype="float32", blocksize=0, latency="low", callback=self._callback,
                )
                self._channels = channels
                self.stream.start()
                return self
            except Exception:
                self.stream = None
        raise RuntimeError(f"无法打开录音设备：{self.info['name']}")

    def _callback(self, indata, frames, time_info, status):
        if status:
            self.error = str(status)
        x = np.asarray(indata[:, 0] if indata.ndim > 1 else indata, dtype=np.float32)
        y = self._resampler.resample_chunk(x, last=False)
        if y.size == 0:
            return
        with self._lock:
            n = y.size
            pos = self.total % self.ring.size
            first = min(n, self.ring.size - pos)
            self.ring[pos:pos + first] = y[:first]
            if first < n:
                self.ring[:n - first] = y[first:]
            self.total += n

    def read(self, start: int, end: int) -> np.ndarray:
        """Return samples [start, end); zeros before stream start or after now."""
        n = max(0, int(end) - int(start))
        out = np.zeros(n, np.float32)
        if n == 0:
            return out
        with self._lock:
            total = self.total
            lo = max(0, int(start))
            hi = min(int(end), total)
            if hi <= lo:
                return out
            count = hi - lo
            pos = lo % self.ring.size
            first = min(count, self.ring.size - pos)
            out[lo - start:lo - start + first] = self.ring[pos:pos + first]
            if first < count:
                out[lo - start + first:lo - start + count] = self.ring[:count - first]
        return out

    def time_at(self, sample: int) -> float:
        return (self.start_time or time.perf_counter()) + int(sample) / self.target_rate

    def stop(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None


class SimAudio:
    """Real-time file playback used to test the pipeline without a microphone."""

    def __init__(self, wav_path: str | Path, target_rate: int = 16000,
                 loop: bool = False, speed: float = 1.0):
        import soundfile as sf
        data, sr = sf.read(str(wav_path), dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        if sr != target_rate:
            import soxr
            data = soxr.resample(data.astype(np.float32), sr, target_rate, quality="HQ")
        self.data = np.asarray(data, np.float32)
        self.target_rate = target_rate
        self.loop = loop
        self.speed = max(0.1, float(speed))
        self.total = 0
        self.start_time = None
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self.start_time = time.perf_counter()
        self._thread = threading.Thread(target=self._run, daemon=True, name="sim-audio")
        self._thread.start()
        return self

    def _run(self):
        t0 = time.perf_counter()
        while not self._stop.is_set():
            target = int((time.perf_counter() - t0) * self.target_rate * self.speed)
            if target > len(self.data) and not self.loop:
                self.total = len(self.data)
                return
            self.total = target
            time.sleep(0.01)

    def read(self, start: int, end: int) -> np.ndarray:
        n = max(0, int(end) - int(start))
        out = np.zeros(n, np.float32)
        if n == 0:
            return out
        lo = max(0, int(start))
        hi = min(int(end), self.total)
        if hi <= lo:
            return out
        off = lo - int(start)
        count = hi - lo
        if self.loop:
            src = lo % len(self.data)
            first = min(count, len(self.data) - src)
            out[off:off + first] = self.data[src:src + first]
            if first < count:
                out[off + first:off + count] = self.data[:count - first]
        else:
            take = min(count, len(self.data) - lo)
            if take > 0:
                out[off:off + take] = self.data[lo:lo + take]
        return out

    def time_at(self, sample: int) -> float:
        return (self.start_time or time.perf_counter()) + int(sample) / self.target_rate

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
