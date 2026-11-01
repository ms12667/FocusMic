"""Make sequential before/after listening files (not left/right A/B).

Order in each file: original input -> 1 s silence -> Falcon output -> 1 s silence.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent / "testrecordings"
SR = 16000


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12)


def fade(x: np.ndarray, ms: float = 10.0) -> np.ndarray:
    n = min(len(x), int(SR * ms / 1000))
    if n <= 1:
        return x
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    y = x.copy()
    y[:n] *= ramp
    y[-n:] *= ramp[::-1]
    return y


def segment(path: str, start: float, end: float) -> np.ndarray:
    x, sr = sf.read(str(ROOT / path), dtype="float32")
    assert sr == SR, (path, sr)
    a, b = int(start * SR), min(int(end * SR), len(x))
    return fade(x[a:b].copy())


def match(x: np.ndarray, db: float = -20.0) -> np.ndarray:
    return (x * (10 ** (db / 20) / rms(x))).astype(np.float32)


def concat(before: np.ndarray, after: np.ndarray, path: str, gap: float = 1.0) -> None:
    gap_samples = np.zeros(int(SR * gap), np.float32)
    out = np.concatenate([before, gap_samples, after, gap_samples])
    sf.write(str(ROOT / path), np.clip(out, -1.0, 1.0), SR, subtype="PCM_16")
    print(f"{path}: {len(out)/SR:.1f}s  before {20*np.log10(rms(before)):.1f} dBFS  "
          f"after {20*np.log10(rms(after)):.1f} dBFS")


def main():
    # Real simultaneous recording: user + friend, user's face in frame.
    start, end = 4.0, 24.0
    real_in = segment("Mixed_16k.wav", start, end)
    real_out = segment("eval_falconbig_real_mixed.wav", start, end)
    concat(match(real_in), match(real_out), "before_after_real_mixed_matched.wav")

    # Same gain for both, so the output's natural level is also audible.
    gain = 10 ** (-20 / 20) / rms(real_in)
    concat((real_in * gain).astype(np.float32), (real_out * gain).astype(np.float32),
           "before_after_real_mixed_samegain.wav")

    # Synthetic mix at -10 dB target-to-interferer, Big output.
    syn_in = segment("eval_mix_snr-10.wav", 2.0, 22.0)
    syn_out = segment("eval_falconbig_snr-10.wav", 2.0, 22.0)
    concat(match(syn_in), match(syn_out), "before_after_synth-10_matched.wav")


if __name__ == "__main__":
    main()
