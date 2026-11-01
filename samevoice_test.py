"""Same-speaker interference test: Falcon (lip-synced target) vs VoxLock (voiceprint only)."""
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

PROBE = Path(__file__).resolve().parent
sys.path.insert(0, str(PROBE / "Falcon" / "studio"))
from falcon_runtime import FalconRuntime, WINDOW_SAMPLES  # noqa: E402
from voxlock.core import loud_sample  # noqa: E402
import voxlock  # noqa: E402

WINDOW, HOP, GUARD, FRAME = WINDOW_SAMPLES, 8000, 1280, 640
x, _ = sf.read(str(PROBE / "demo" / "small_falcon.wav"), dtype="float32")
target = x[10 * 16000 : 30 * 16000].copy()
interf = x[60 * 16000 : 80 * 16000].copy()
n = min(len(target), len(interf))
target, interf = target[:n], interf[:n]
target /= np.sqrt(np.mean(target**2)) + 1e-12
interf /= np.sqrt(np.mean(interf**2)) + 1e-12
mix = target + interf
s = 0.9 / float(np.max(np.abs(mix)))
target *= s
interf *= s
mix = target + interf
sf.write(str(PROBE / "demo" / "samevoice_mix.wav"), mix, 16000, subtype="PCM_16")
sf.write(str(PROBE / "demo" / "samevoice_target.wav"), target, 16000, subtype="PCM_16")
sf.write(str(PROBE / "demo" / "samevoice_interf.wav"), interf, 16000, subtype="PCM_16")

# Falcon with the target's mouth video
mouth = np.load(PROBE / "demo" / "seg_mouth_+0.npy")
rt = FalconRuntime("small", str(PROBE / "weights" / "falcon.pt")).load("cuda")
out = np.zeros(len(mix), np.float32)
for e in range(WINDOW, len(mix) + 1, HOP):
    start = max(0, (e - WINDOW) // FRAME)
    f = mouth[start : start + 50]
    if len(f) < 50:
        break
    pred = rt.infer(mix[e - WINDOW : e], np.ascontiguousarray(f))
    seg = pred[WINDOW - GUARD - HOP : WINDOW - GUARD]
    out[e - GUARD - HOP : e - GUARD] = seg
sf.write(str(PROBE / "demo" / "samevoice_falcon.wav"), out, 16000, subtype="PCM_16")

# VoxLock with a clean 3 s target enrollment
vl = voxlock.VoxLock(precision="int8")
sample = loud_sample(target, sec=3.0)
vox = vl.isolate(mix, sample=sample)
sf.write(str(PROBE / "demo" / "samevoice_voxlock.wav"), vox, 16000, subtype="PCM_16")

# Metrics against the exact target component (skip the first 2 s context)
sl = slice(2 * 16000, len(mix) - 3200)
t = target[sl]


def metrics(est, name):
    e = est[sl]
    alpha = float(np.dot(e, t) / (np.dot(t, t) + 1e-12))
    proj = alpha * t
    si = 10 * np.log10(np.sum(proj**2) / (np.sum((e - proj) ** 2) + 1e-12))
    A = np.stack([target[sl], interf[sl]], 1)
    w, *_ = np.linalg.lstsq(A, e, rcond=None)
    sir = 20 * np.log10(abs(w[0]) / (abs(w[1]) + 1e-12) + 1e-12)
    print(f"{name}: corr {np.corrcoef(e, t)[0,1]:.4f}  SI-SDR {si:6.1f} dB  "
          f"target weight {w[0]:.3f}  interferer weight {w[1]:.3f}  SIR {sir:5.1f} dB")


metrics(out, "Falcon  ")
metrics(vox, "VoxLock ")
