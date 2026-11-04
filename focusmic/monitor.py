"""Optional headphone monitor output for the native pipeline."""
from __future__ import annotations

import queue
import threading
import time

import numpy as np


def resolve_monitor_device(sd) -> tuple[int, str]:
    """Follow the Windows default playback endpoint, not an arbitrary WASAPI one.

    PortAudio lists the same physical endpoint once per host API
    (MME/DirectSound/WASAPI/WDM-KS).  Preferring WASAPI without checking its
    default_output_device used to pick the *other* endpoint (e.g. speakers
    instead of the current headphones).
    """
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()

    def usable(index) -> bool:
        if index is None or not 0 <= int(index) < len(devices):
            return False
        d = devices[int(index)]
        name = str(d["name"]).upper()
        return (int(d["max_output_channels"]) >= 2
                and "CABLE" not in name and "VB-AUDIO" not in name)

    def describe(index: int) -> tuple[int, str]:
        d = devices[index]
        api = str(hostapis[int(d["hostapi"])]["name"])
        return index, f"{d['name']} [{api}]"

    # 1) Windows' current default in WASAPI (the same endpoint Windows shows
    #    in the volume flyout).
    wasapi = next(
        (i for i, api in enumerate(hostapis) if "WASAPI" in str(api["name"])),
        None)
    if wasapi is not None:
        index = int(hostapis[wasapi].get("default_output_device", -1))
        if usable(index):
            return describe(index)

    # 2) PortAudio's default output, whatever host API it belongs to.
    index = int(sd.default.device[1])
    if usable(index):
        return describe(index)

    # 3) Fallback: prefer a WASAPI endpoint that is not a virtual cable.
    candidates = []
    for i, d in enumerate(devices):
        if not usable(i):
            continue
        api = str(hostapis[int(d["hostapi"])]["name"])
        candidates.append((
            0 if "WASAPI" in api else 1,
            abs(float(d["default_samplerate"]) - 48000.0),
            i, str(d["name"]), api,
        ))
    if not candidates:
        raise RuntimeError("找不到耳机/扬声器输出设备。")
    candidates.sort()
    _, _, idx, name, api = candidates[0]
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
        self.latency = 0.0
        self._queue = None
        self._stream = None
        self._thread = None
        self._stop = threading.Event()

    def start(self) -> dict:
        self.stop()
        import sounddevice as sd
        idx, name = resolve_monitor_device(sd)
        info = sd.query_devices(idx)
        self.samplerate = int(round(float(info.get("default_samplerate", 48000)))) or 48000
        self._queue = queue.Queue(maxsize=self.max_queue)
        self._stop.clear()
        self._stream = sd.OutputStream(
            device=idx, samplerate=self.samplerate, channels=2,
            dtype="float32", blocksize=self.blocksize, latency="low",
        )
        self._stream.start()
        self.latency = float(getattr(self._stream, "latency", 0.0) or 0.0)
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
        try:
            import soxr
        except Exception as exc:
            self.error = f"soxr: {exc}"
            self.active = False
            return
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
            "latency": self.latency,
            "samplerate": self.samplerate,
            "gain_db": float(round(20 * np.log10(self.gain + 1e-12), 1)),
        }
