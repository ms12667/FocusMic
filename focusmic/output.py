"""Low-latency Windows output to VB-CABLE, bypassing the browser media element.

The server produces 16 kHz mono chunks every hop. This class resamples them to
the CABLE device rate and writes them through WASAPI. It is intentionally small
and dependency-light; import sounddevice/soxr lazily so the server can still
start on machines without an audio device.
"""
from __future__ import annotations

import queue
import threading
import time

import numpy as np


def resolve_cable_input(sd) -> tuple[int, str]:
    """Pick the 2-channel CABLE Input, preferring WASAPI at 48 kHz."""
    devices = sd.query_devices()
    candidates = []
    for i, d in enumerate(devices):
        name = str(d["name"])
        if "CABLE Input" not in name or int(d["max_output_channels"]) < 2:
            continue
        if "16ch" in name:
            continue
        api = str(sd.query_hostapis(int(d["hostapi"]))["name"])
        score = 0
        if "WASAPI" in api:
            score += 4
        if int(d["max_output_channels"]) == 2:
            score += 2
        if abs(float(d["default_samplerate"]) - 48000.0) < 1:
            score += 1
        candidates.append((score, i, name, api))
    if not candidates:
        raise RuntimeError("找不到 CABLE Input（VB-Audio Virtual Cable）。请先安装 VB-CABLE。")
    candidates.sort(reverse=True)
    _, idx, name, api = candidates[0]
    return idx, f"{name} [{api}]"


class CableOutput:
    """A small jitter-buffered writer for server-side CABLE output."""

    def __init__(self, gain: float = 2.0, blocksize: int = 480, max_queue: int = 4, prebuffer: int = 2):
        self.gain = float(gain)
        self.blocksize = int(blocksize)
        self.max_queue = int(max_queue)
        self.prebuffer = max(1, int(prebuffer))
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
        idx, name = resolve_cable_input(sd)
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
        self._thread = threading.Thread(target=self._writer, daemon=True, name="cable-output")
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
            # Keep the newest audio rather than growing latency.
            try:
                self._queue.get_nowait()
                self.dropped += 1
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(x)
            except queue.Full:
                self.dropped += 1

    def reset(self) -> None:
        if self._queue is not None:
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break

    def _writer(self) -> None:
        try:
            import soxr
        except Exception as exc:
            self.error = f"soxr: {exc}"
            self.active = False
            return
        silence = np.zeros((self.blocksize, 2), np.float32)
        # Wait for a small lookahead so fixed-size device writes do not
        # underrun between 200 ms model chunks.
        while not self._stop.is_set() and self._queue.qsize() < self.prebuffer:
            time.sleep(0.01)
        while not self._stop.is_set():
            try:
                chunk = self._queue.get(timeout=0.05)
            except queue.Empty:
                # Underrun: write a short silence block. The model normally
                # produces a chunk every 200 ms, so this is rare and bounded.
                try:
                    if self._stream is None:
                        break
                    self._stream.write(silence)
                    self.underruns += 1
                except Exception as exc:  # device removed / stream stopped
                    if not self._stop.is_set():
                        self.error = str(exc)
                    break
                continue
            try:
                # Stateless per-chunk resampling returns exactly 3x samples for
                # a 3200-sample hop; a streaming resampler returns variable
                # lengths (8808/10276) and causes gaps when written immediately.
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
            "active": self.active,
            "device": self.device,
            "error": self.error,
            "queued": self._queue.qsize() if self._queue is not None else 0,
            "dropped": self.dropped,
            "underruns": self.underruns,
            "latency": self.latency,
            "gain_db": float(round(20 * np.log10(self.gain + 1e-12), 1)),
            "samplerate": self.samplerate,
        }
