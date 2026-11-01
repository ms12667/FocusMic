"""Windowed inference with Studio-style crossfade, mouth offset, and A/B-free
before/after exports."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

PROBE = Path(__file__).resolve().parent
ROOT = PROBE / "testrecordings"
sys.path.insert(0, str(PROBE / "Falcon" / "studio"))
from falcon_runtime import FalconRuntime, WINDOW_SAMPLES  # noqa: E402

WINDOW, GUARD, FRAME = WINDOW_SAMPLES, 1280, 640
FADE = 320


def shift_mouth(mouth: np.ndarray, offset: int) -> np.ndarray:
    if offset == 0:
        return mouth
    if offset > 0:
        return mouth[offset:]
    return np.pad(mouth, ((-offset, 0), (0, 0), (0, 0)), mode="edge")


def windowed(rt, audio: np.ndarray, mouth: np.ndarray, hop: int = 8000,
             offset: int = 0, xfade: bool = True) -> np.ndarray:
    mouth = shift_mouth(mouth, offset)
    out = np.zeros(len(audio), np.float32)
    future = None
    last_e = None
    for e in range(WINDOW, len(audio) + 1, hop):
        start = max(0, (e - WINDOW) // FRAME)
        frames = mouth[start:start + 50]
        if len(frames) < 50:
            break
        pred = rt.infer(audio[e - WINDOW:e], np.ascontiguousarray(frames))
        stop = WINDOW - GUARD
        chunk = pred[stop - hop:stop].copy()
        s = e - GUARD - hop
        if xfade and future is not None and last_e is not None and e - last_e == hop:
            ramp = np.linspace(0, 1, FADE, dtype=np.float32)
            chunk[:FADE] = future * (1 - ramp) + chunk[:FADE] * ramp
        future = pred[stop:stop + FADE].copy()
        out[s:s + len(chunk)] = chunk
        last_e = e
    return out


def rms(x):
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12)


def metrics(est, target, interf, start=32000, pad=3200):
    sl = slice(start, len(est) - pad)
    e = est[sl].astype(np.float64)
    t = target[sl].astype(np.float64)
    i = interf[sl].astype(np.float64)
    m = min(len(e), len(t), len(i))
    e, t, i = e[:m], t[:m], i[:m]
    a = np.dot(e, t) / (np.dot(t, t) + 1e-12)
    proj = a * t
    si = 10 * np.log10(np.sum(proj ** 2) / (np.sum((e - proj) ** 2) + 1e-12))
    tn, inn = t / rms(t), i / rms(i)
    w, *_ = np.linalg.lstsq(np.stack([tn, inn], 1), e, rcond=None)
    sir = 20 * np.log10(abs(w[0]) / (abs(w[1]) + 1e-12) + 1e-12)
    return float(np.corrcoef(e, t)[0, 1]), float(si), float(sir), float(20 * np.log10(rms(est) + 1e-12))


def fade(x, ms=10.0):
    n = min(len(x), int(16000 * ms / 1000))
    y = x.copy()
    r = np.linspace(0, 1, n, dtype=np.float32)
    y[:n] *= r
    y[-n:] *= r[::-1]
    return y


def match(x, db=-20.0):
    return (x * (10 ** (db / 20) / rms(x))).astype(np.float32)


def before_after(before, after, name, samegain=False):
    start, end = 10.0, 20.0
    b = fade(before[int(start * 16000):int(end * 16000)].copy())
    a = fade(after[int(start * 16000):int(end * 16000)].copy())
    if samegain:
        g = 10 ** (-20 / 20) / rms(b)
        b, a = (b * g).astype(np.float32), (a * g).astype(np.float32)
    else:
        b, a = match(b), match(a)
    gap = np.zeros(int(16000 * 0.8), np.float32)
    y = np.concatenate([b, gap, a, gap])
    sf.write(str(ROOT / name), np.clip(y, -1, 1), 16000, subtype="PCM_16")
    print(f"  {name}: before {20*np.log10(rms(b)):.1f} dBFS, after {20*np.log10(rms(a)):.1f} dBFS")


def main():
    me, _ = sf.read(str(ROOT / "Me-only-clear_16k.wav"), dtype="float32")
    fr, _ = sf.read(str(ROOT / "Friend-only-clear_16k.wav"), dtype="float32")
    n = min(len(me), len(fr))
    me, fr = me[:n], fr[:n]
    mouth_me = np.load(ROOT / "Me-only-clear_mouth25.npy")
    mixed, _ = sf.read(str(ROOT / "Mixed_16k.wav"), dtype="float32")
    mouth_mixed = np.load(ROOT / "Mixed_mouth25.npy")

    big = FalconRuntime("big", str(PROBE / "weights" / "falcon-big.pt")).load("cuda")

    print("synthetic -10 dB:")
    mix10, _ = sf.read(str(ROOT / "eval_mix_snr-10.wav"), dtype="float32")
    for off in (0, 1):
        t0 = time.perf_counter()
        out = windowed(big, mix10, mouth_me, offset=off, xfade=True)
        print(f"  offset {off:+d}: {time.perf_counter()-t0:.2f}s", metrics(out, me, fr))
        sf.write(str(ROOT / f"eval_big_xfade_snr-10_off{off:+d}.wav"), out, 16000, subtype="PCM_16")
        if off == 1:
            before_after(mix10, out, "before_after_synth-10_xfade.wav")

    print("real mixed:")
    for off in (0, 1):
        t0 = time.perf_counter()
        out = windowed(big, mixed, mouth_mixed, offset=off, xfade=True)
        print(f"  offset {off:+d}: {time.perf_counter()-t0:.2f}s rms {20*np.log10(rms(out)):.1f} dBFS")
        sf.write(str(ROOT / f"eval_big_xfade_real_mixed_off{off:+d}.wav"), out, 16000, subtype="PCM_16")
        before_after(mixed, out, f"before_after_real_mixed_xfade_off{off:+d}.wav")
        if off == 1:
            before_after(mixed, out, "before_after_real_mixed_xfade_samegain.wav", samegain=True)


if __name__ == "__main__":
    main()
