"""Benchmark Falcon on this machine: per-window inference latency and VRAM."""
import sys
import time
from pathlib import Path

import numpy as np
import torch

PROBE = Path(__file__).resolve().parent
STUDIO = PROBE / "Falcon" / "studio"
sys.path.insert(0, str(STUDIO))

from falcon_runtime import FalconRuntime, WINDOW_FRAMES, WINDOW_SAMPLES  # noqa: E402

CKPT = PROBE / "weights" / "falcon.pt"
variant = sys.argv[1] if len(sys.argv) > 1 else "small"
device = sys.argv[2] if len(sys.argv) > 2 else "cuda"
ckpt = PROBE / "weights" / ("falcon.pt" if variant == "small" else "falcon-big.pt")

rt = FalconRuntime(variant, str(ckpt)).load(device)
print("status:", rt.status())
print("params:", rt.parameter_count)

rng = np.random.default_rng(0)
audio = (rng.standard_normal(WINDOW_SAMPLES) * 0.05).astype(np.float32)
frames = rng.integers(0, 255, (WINDOW_FRAMES, 96, 96), dtype=np.uint8)

for _ in range(5):
    rt.infer(audio, frames)
if device == "cuda":
    torch.cuda.synchronize()

times = []
for _ in range(30):
    t0 = time.perf_counter()
    out = rt.infer(audio, frames)
    if device == "cuda":
        torch.cuda.synchronize()
    times.append((time.perf_counter() - t0) * 1000.0)

t = np.array(times)
print(f"{variant}/{device}: mean {t.mean():.2f} ms  p50 {np.percentile(t,50):.2f}  "
      f"p95 {np.percentile(t,95):.2f}  min {t.min():.2f}  max {t.max():.2f}")
print("output:", out.shape, out.dtype, "finite", bool(np.isfinite(out).all()))
if device == "cuda":
    print("VRAM allocated %.1f MB, reserved %.1f MB" % (
        torch.cuda.max_memory_allocated() / 2**20, torch.cuda.max_memory_reserved() / 2**20))
