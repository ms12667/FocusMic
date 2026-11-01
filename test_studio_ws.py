"""Exercise the running Falcon Studio WebSocket at the 0.2 s hop with real audio."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import websockets
from PIL import Image

PROBE = Path(__file__).resolve().parent
ROOT = PROBE / "testrecordings"
URL = "ws://127.0.0.1:7860/ws"
WINDOW, HOP, GUARD, FRAME = 32000, 3200, 1280, 640
N_WINDOWS = 10


def b64_audio(x: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(x, dtype="<f4").tobytes()).decode("ascii")


def b64_frames(crops: np.ndarray) -> list[str]:
    out = []
    for crop in crops:
        buf = io.BytesIO()
        Image.fromarray(crop, mode="L").save(buf, format="JPEG", quality=88)
        out.append(base64.b64encode(buf.getvalue()).decode("ascii"))
    return out


async def main():
    audio, sr = sf.read(str(ROOT / "synth_adj_snr0_mix.wav"), dtype="float32")
    mouth = np.load(ROOT / "Me-only-clear_mouth25.npy")
    assert sr == 16000
    result = np.zeros(len(audio), np.float32)
    latencies = []
    async with websockets.connect(URL, max_size=4_000_000) as ws:
        for i in range(N_WINDOWS):
            e = WINDOW + i * HOP
            start = (e - WINDOW) // FRAME
            frames = mouth[start:start + 50]
            if len(frames) < 50:
                break
            req = {
                "type": "infer", "id": i,
                "audio": b64_audio(audio[e - WINDOW:e]),
                "frames": b64_frames(np.ascontiguousarray(frames)),
                "window_seconds": 2, "hop_seconds": HOP / 16000,
                "end_sample": e, "reset": i == 0,
            }
            t0 = time.perf_counter()
            await ws.send(json.dumps(req))
            resp = json.loads(await ws.recv())
            dt = (time.perf_counter() - t0) * 1000
            if resp.get("type") != "result":
                raise RuntimeError(resp)
            samples = np.frombuffer(base64.b64decode(resp["audio"]), dtype="<f4").copy()
            assert samples.shape == (HOP,), (samples.shape, resp)
            s = resp["start_sample"]
            result[max(0, s):max(0, s) + len(samples)] = samples
            latencies.append((dt, resp["inference_ms"], resp["contiguous"]))
            print(f"window {i}: e={e} roundtrip {dt:.1f} ms, server infer {resp['inference_ms']} ms, "
                  f"contiguous={resp['contiguous']}, clipped={resp['clipped_samples']}")
    sf.write(str(ROOT / "studio_ws_out_hop200.wav"), result, 16000, subtype="PCM_16")
    print("wrote studio_ws_out_hop200.wav; roundtrip mean",
          float(np.mean([x[0] for x in latencies])), "ms")

    off, _ = sf.read(str(ROOT / "synth_adj_snr0_hop3200_nomu.wav"), dtype="float32")
    n = min(len(off), len(result))
    a, b = off[:n], result[:n]
    mask = np.abs(a) + np.abs(b) > 1e-6
    if mask.any():
        print("corr with offline:", float(np.corrcoef(a[mask], b[mask])[0, 1]),
              "max abs diff:", float(np.max(np.abs(a - b))))


if __name__ == "__main__":
    asyncio.run(main())
