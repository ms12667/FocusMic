"""Audio input sources for the native FocusMic pipeline."""
from __future__ import annotations

import threading
import time
from collections import deque
from pathlib import Path

import numpy as np

from .i18n import t


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


def _device_match_key(name: str) -> str:
    """Normalize PortAudio names so truncated MME entries match their twins."""
    text = str(name or "").lower().replace("(", " ").replace(")", " ")
    return " ".join(text.split())


def _same_endpoint(left: str, right: str) -> bool:
    if left == right:
        return True
    short, long = sorted((left, right), key=len)
    if len(short) < 8:
        return False
    return long.startswith(short) and len(short) / len(long) >= 0.65


def _input_device_score(device: dict) -> int:
    """Prefer the modern WASAPI endpoint over the same device's legacy twins."""
    api = str(device.get("hostapi", "")).upper()
    score = 0
    if "WASAPI" in api:
        score += 400
    elif "DIRECTSOUND" in api:
        score += 300
    elif "MME" in api:
        score += 200
    elif "WDM-KS" in api:
        score += 100
    try:
        score += min(40, int(round(float(device.get("samplerate", 0)) / 1200)))
    except (TypeError, ValueError):
        pass
    return score


def recommended_input_devices(devices: list[dict], show_all: bool = False) -> list[dict]:
    """Collapse PortAudio's per-host-API duplicates into one entry per endpoint.

    PortAudio lists the same physical microphone once for MME, DirectSound,
    WASAPI and WDM-KS. A first-run user should not have to understand that.
    The default list keeps only WASAPI endpoints (the modern Windows API);
    if a machine exposes no WASAPI input at all, fall back to one best-scored
    entry per name and mark the collapsed ones as recommended. With
    ``show_all`` the raw list is returned unchanged for troubleshooting.
    """
    if show_all:
        return [dict(device) for device in devices]
    groups: list[dict] = []
    for device in devices:
        key = _device_match_key(device.get("name", ""))
        group = next(
            (item for item in groups if _same_endpoint(key, item["key"])), None)
        if group is None:
            groups.append({"key": key, "items": [device]})
        else:
            group["items"].append(device)
            if len(key) > len(group["key"]):
                group["key"] = key
    deduped = []
    for group in groups:
        representative = dict(max(group["items"], key=_input_device_score))
        representative["recommended"] = len(group["items"]) > 1
        representative["hostapi_count"] = len({
            str(device.get("hostapi", "")) for device in group["items"]})
        deduped.append(representative)
    wasapi = [device for device in deduped
              if "WASAPI" in str(device.get("hostapi", "")).upper()]
    if wasapi:
        # When every visible row is WASAPI the badge would be noise.
        for device in wasapi:
            device["recommended"] = False
        return wasapi
    return deduped


def input_device_label(device: dict) -> str:
    text = f"{device['name']}  ·  {device['hostapi']}"
    if device.get("recommended"):
        text += f"  ·  {t('home.device.recommended')}"
    return text


def visible_input_devices(sd, show_all: bool = False) -> list[dict]:
    return recommended_input_devices(list_input_devices(sd), show_all=show_all)


def resolve_input(sd, spec: str | int | None) -> tuple[int, dict]:
    devices = list_input_devices(sd)
    if not devices:
        raise RuntimeError(t("error.no_input"))
    if spec is None or spec == "":
        wanted = sd.default.device[0]
        # Prefer a physical WASAPI endpoint at 48 kHz over MME/DirectSound
        # duplicates, and never default to a virtual cable/Steam mic.
        physical = [d for d in devices
                    if "CABLE" not in d["name"].upper() and "STEAM" not in d["name"].upper()]
        pool = physical or devices
        pool.sort(key=lambda d: (
            "WASAPI" not in d["hostapi"],
            abs(d["samplerate"] - 48000.0),
            d["index"] != wanted,
            d["index"],
        ))
        return pool[0]["index"], pool[0]
    if isinstance(spec, int) or str(spec).isdigit():
        idx = int(spec)
        for d in devices:
            if d["index"] == idx:
                return idx, d
        raise RuntimeError(t("error.mic_index", index=idx))
    needle = str(spec).lower()
    matches = [d for d in devices if needle in d["name"].lower()]
    if not matches:
        raise RuntimeError(t("error.mic_name", spec=repr(spec)))
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
        self.latency = 0.0
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
                self.latency = float(getattr(self.stream, "latency", 0.0) or 0.0)
                return self
            except Exception:
                self.stream = None
        raise RuntimeError(t("error.open_mic", name=self.info["name"]))

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
