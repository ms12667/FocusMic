"""Synthetic mixes from Me-only + Friend-only, with the friend attenuated to
compensate for the near-mic recording. Tests Falcon-Big suppression."""
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

WINDOW, GUARD, FRAME, FADE = WINDOW_SAMPLES, 1280, 640, 320


def rms(x):
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12)


def mix_at_snr(target, interf, snr_db):
    """Keep target at its original level; scale interferer to the requested SNR."""
    scale = rms(target) / (10 ** (snr_db / 20.0)) / rms(interf)
    mix = target + interf * scale
    peak = float(np.max(np.abs(mix)))
    if peak > 0.98:
        mix *= 0.98 / peak
    return mix.astype(np.float32), 20 * np.log10(scale + 1e-12)


def mu_law(x, mu):
    return (np.sign(x) * np.log1p(mu * np.abs(x)) / np.log1p(mu)).astype(np.float32)


def mu_inv(y, mu):
    return (np.sign(y) * np.expm1(np.abs(y) * np.log1p(mu)) / mu).astype(np.float32)


def windowed(rt, audio, mouth, hop, mu=None):
    x = mu_law(audio, mu) if mu else audio
    out = np.zeros(len(x), np.float32)
    future = None
    last = None
    for e in range(WINDOW, len(x) + 1, hop):
        start = max(0, (e - WINDOW) // FRAME)
        frames = mouth[start:start + 50]
        if len(frames) < 50:
            break
        pred = rt.infer(x[e - WINDOW:e], np.ascontiguousarray(frames))
        stop = WINDOW - GUARD
        chunk = pred[stop - hop:stop].copy()
        s = e - GUARD - hop
        if future is not None and last is not None and e - last == hop:
            ramp = np.linspace(0, 1, FADE, dtype=np.float32)
            chunk[:FADE] = future * (1 - ramp) + chunk[:FADE] * ramp
        future = pred[stop:stop + FADE].copy()
        out[s:s + len(chunk)] = chunk
        last = e
    return mu_inv(out, mu) if mu else out


def metrics(est, target, interf):
    sl = slice(32000, len(est) - 3200)
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


def fade(x, ms=10):
    n = min(len(x), int(16000 * ms / 1000))
    y = x.copy()
    r = np.linspace(0, 1, n, dtype=np.float32)
    y[:n] *= r
    y[-n:] *= r[::-1]
    return y


def match(x, db=-20.0):
    return (x * (10 ** (db / 20) / rms(x))).astype(np.float32)


def before_after(before, after, name, samegain=False, start=1.0, end=21.0):
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
    print(f"  {name}: before {20*np.log10(rms(b)):.1f} / after {20*np.log10(rms(a)):.1f} dBFS")


def main():
    me, sr = sf.read(str(ROOT / "Me-only-clear_16k.wav"), dtype="float32")
    fr, _ = sf.read(str(ROOT / "Friend-only-clear_16k.wav"), dtype="float32")
    n = min(len(me), len(fr))
    me, fr = me[:n], fr[:n]
    mouth = np.load(ROOT / "Me-only-clear_mouth25.npy")
    print(f"me {20*np.log10(rms(me)):.1f} dBFS, friend {20*np.log10(rms(fr)):.1f} dBFS, "
          f"friend is {20*np.log10(rms(fr)/rms(me)):.1f} dB louder")

    big = FalconRuntime("big", str(PROBE / "weights" / "falcon-big.pt")).load("cuda")

    for snr in (0.0, -3.0, -6.0):
        mix, scale_db = mix_at_snr(me, fr, snr)
        print(f"\n=== target/friend SNR {snr:+.0f} dB (friend attenuated {scale_db:+.1f} dB) ===")
        sf.write(str(ROOT / f"synth_adj_snr{int(snr)}_mix.wav"), mix, 16000, subtype="PCM_16")

        t0 = time.perf_counter()
        base = windowed(big, mix, mouth, 8000, mu=None)
        print(f"  baseline 0.5s: {time.perf_counter()-t0:.1f}s", metrics(base, me, fr))
        sf.write(str(ROOT / f"synth_adj_snr{int(snr)}_baseline.wav"), base, 16000, subtype="PCM_16")

        t0 = time.perf_counter()
        best = windowed(big, mix, mouth, 3200, mu=3)
        print(f"  mu3 0.2s:     {time.perf_counter()-t0:.1f}s", metrics(best, me, fr))
        sf.write(str(ROOT / f"synth_adj_snr{int(snr)}_mu3_hop200.wav"), best, 16000, subtype="PCM_16")

        if snr in (0.0, -3.0):
            before_after(mix, best, f"before_after_synth_adj_snr{int(snr)}_mu3_hop200.wav")
            if snr == 0.0:
                before_after(mix, best, "before_after_synth_adj_snr0_mu3_hop200_samegain.wav", samegain=True)
                before_after(mix, base, "before_after_synth_adj_snr0_baseline.wav")


if __name__ == "__main__":
    main()
