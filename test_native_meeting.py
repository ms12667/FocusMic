"""End-to-end test of server-side CABLE output (no browser, no microphone)."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
import soxr
import websockets
from PIL import Image
from scipy.signal import correlate

PROBE = Path(__file__).resolve().parent
ROOT = PROBE / "testrecordings"
URL = "http://127.0.0.1:7860"
WS = "ws://127.0.0.1:7860/ws"
WINDOW, HOP, GUARD, FRAME = 32000, 3200, 1280, 640


def post_meeting(enabled: bool):
    req = urllib.request.Request(
        URL + "/api/meeting",
        data=json.dumps({"enabled": enabled}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


def b64_audio(x):
    return base64.b64encode(np.ascontiguousarray(x, dtype="<f4").tobytes()).decode()


def b64_frames(crops):
    out = []
    for crop in crops:
        buf = io.BytesIO()
        Image.fromarray(crop, mode="L").save(buf, format="JPEG", quality=88)
        out.append(base64.b64encode(buf.getvalue()).decode())
    return out


async def main():
    audio, sr = sf.read(str(ROOT / "synth_adj_snr0_mix.wav"), dtype="float32")
    mouth = np.load(ROOT / "Me-only-clear_mouth25.npy")
    assert sr == 16000
    devs = sd.query_devices()
    in_i = next(i for i, d in enumerate(devs)
                if d["name"].startswith("CABLE Output") and d["max_input_channels"] == 2
                and "WASAPI" in sd.query_hostapis(d["hostapi"])["name"])
    rec = []
    def callback(indata, frames, t, status):
        rec.append(indata.copy())
    inp = sd.InputStream(device=in_i, samplerate=48000, channels=2, dtype="float32",
                         blocksize=0, latency="low", callback=callback)
    print("meeting:", post_meeting(True))
    inp.start()
    expected = np.zeros(len(audio) * 3, np.float32)
    try:
        async with websockets.connect(WS, max_size=4_000_000) as ws:
            t0 = time.perf_counter()
            for i in range(15):
                e = WINDOW + i * HOP
                start = (e - WINDOW) // FRAME
                frames = mouth[start:start + 50]
                req = {
                    "type": "infer", "id": i,
                    "audio": b64_audio(audio[e - WINDOW:e]),
                    "frames": b64_frames(np.ascontiguousarray(frames)),
                    "window_seconds": 2, "hop_seconds": 0.2,
                    "end_sample": e, "reset": i == 0,
                }
                await ws.send(json.dumps(req))
                resp = json.loads(await ws.recv())
                if resp.get("type") != "result":
                    raise RuntimeError(resp)
                chunk = np.frombuffer(base64.b64decode(resp["audio"]), dtype="<f4").copy()
                y = soxr.resample(chunk, 16000, 48000, quality="HQ") * 2.0
                s = resp["start_sample"] * 3
                expected[s:s + len(y)] = np.clip(y, -1, 1)
                # pace like the browser (5 windows/s)
                delay = t0 + (i + 1) * 0.2 - time.perf_counter()
                if delay > 0:
                    await asyncio.sleep(delay)
            await asyncio.sleep(0.8)
    finally:
        inp.stop()
        inp.close()
        print("meeting off:", post_meeting(False))

    recorded = np.concatenate(rec).mean(axis=1).astype(np.float64)
    ref = expected.astype(np.float64)
    mask = np.abs(ref) > 1e-6
    print("recorded", len(recorded) / 48000, "s, rms", np.sqrt(np.mean(recorded ** 2)),
          "expected rms", np.sqrt(np.mean(ref ** 2)))
    c = correlate(recorded, ref, mode="full")
    lag = np.argmax(np.abs(c)) - (len(ref) - 1)
    norm = np.sqrt(np.sum(recorded ** 2) * np.sum(ref ** 2))
    print("corr", c[np.argmax(np.abs(c))] / norm, "lag ms", lag / 48000 * 1000)
    sf.write(str(ROOT / "native_meeting_rec.wav"), np.stack([recorded, recorded], 1).astype(np.float32),
             48000, subtype="PCM_16")


if __name__ == "__main__":
    asyncio.run(main())
