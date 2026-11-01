"""Windowed Falcon inference on the demo clip: 2 s window, 0.5 s hop, 80 ms guard."""
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

PROBE = Path(__file__).resolve().parent
sys.path.insert(0, str(PROBE / "Falcon" / "studio"))
from falcon_runtime import FalconRuntime, WINDOW_SAMPLES  # noqa: E402

WINDOW = WINDOW_SAMPLES          # 32000
HOP = 8000                       # 0.5 s
GUARD = 1280                     # 80 ms right context
FRAME = 640                      # 16000 / 25 fps

audio, sr = sf.read(str(PROBE / "demo" / "small_mix.wav"), dtype="float32")
if sr != 16000:
    raise SystemExit("need 16 kHz audio")
mouth = np.load(PROBE / "demo" / "small_mouth.npy")
rt = FalconRuntime("small", str(PROBE / "weights" / "falcon.pt")).load("cuda")
print("loaded", rt.status()["device"], "warmup", rt.warmup_ms, "ms")

out = np.zeros(len(audio), np.float32)
windows = 0
t0 = time.perf_counter()
for e in range(WINDOW, len(audio) + 1, HOP):
    a = audio[e - WINDOW : e]
    start = max(0, (e - WINDOW) // FRAME)
    f = mouth[start : start + 50]
    if len(f) < 50:
        break
    pred = rt.infer(a, np.ascontiguousarray(f))
    out[e - GUARD - HOP : e - GUARD] = pred[WINDOW - GUARD - HOP : WINDOW - GUARD]
    windows += 1
    if windows % 40 == 0:
        print(f"  window {windows} ({e / 16000:.1f}s)", flush=True)

elapsed = time.perf_counter() - t0
sf.write(str(PROBE / "demo" / "our_falcon_windowed.wav"), out, 16000, subtype="PCM_16")
print(f"windows {windows}, elapsed {elapsed:.2f}s, audio {len(audio)/16000:.2f}s, "
      f"RTF {elapsed/(len(audio)/16000):.3f}")
if torch.cuda.is_available():
    print("VRAM allocated %.1f MB, reserved %.1f MB" % (
        torch.cuda.max_memory_allocated() / 2**20, torch.cuda.max_memory_reserved() / 2**20))
