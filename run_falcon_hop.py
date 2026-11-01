"""Windowed Falcon inference with a configurable hop, for the 30 s demo segment."""
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

PROBE = Path(__file__).resolve().parent
sys.path.insert(0, str(PROBE / "Falcon" / "studio"))
from falcon_runtime import FalconRuntime, WINDOW_SAMPLES  # noqa: E402

WINDOW = WINDOW_SAMPLES
GUARD = 1280
FRAME = 640

audio, _ = sf.read(str(PROBE / "demo" / "seg_mix.wav"), dtype="float32")
mouth = np.load(PROBE / "demo" / "seg_mouth_+0.npy")
rt = FalconRuntime("small", str(PROBE / "weights" / "falcon.pt")).load("cuda")

for hop_ms, hop in [(100, 1600), (200, 3200), (500, 8000)]:
    out = np.zeros(len(audio), np.float32)
    t0 = time.perf_counter()
    count = 0
    for e in range(WINDOW, len(audio) + 1, hop):
        start = max(0, (e - WINDOW) // FRAME)
        f = mouth[start : start + 50]
        if len(f) < 50:
            break
        pred = rt.infer(audio[e - WINDOW : e], np.ascontiguousarray(f))
        seg = pred[WINDOW - GUARD - hop : WINDOW - GUARD]
        s = e - GUARD - hop
        out[s : s + len(seg)] = seg
        count += 1
    dt = time.perf_counter() - t0
    name = f"hop{hop_ms}"
    sf.write(str(PROBE / "demo" / f"seg_{name}.wav"), out, 16000, subtype="PCM_16")
    print(f"{name}: windows {count}, elapsed {dt:.2f}s, RTF {dt/(len(audio)/16000):.3f}")
