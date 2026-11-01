"""Evaluate Falcon vs VoxLock on the user's real recordings.

Synthetic objective test: Me-only (target) + Friend-only (interferer) at several
SNRs, with the target's mouth video. Real test: Mixed.mp4 with its own mouth.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

PROBE = Path(__file__).resolve().parent
sys.path.insert(0, str(PROBE / "Falcon" / "studio"))
from falcon_runtime import FalconRuntime, WINDOW_SAMPLES  # noqa: E402

WINDOW, GUARD, FRAME = WINDOW_SAMPLES, 1280, 640


def rms(x):
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12)


def mix_at_snr(target, interf, snr_db):
    """Scale the interferer so 20log10(rms(target)/rms(interf)) == snr_db."""
    scale = rms(target) / (10 ** (snr_db / 20.0)) / rms(interf)
    mix = target + interf * scale
    peak = float(np.max(np.abs(mix)))
    if peak > 0.98:
        mix *= 0.98 / peak
    return mix.astype(np.float32), scale


def falcon_windowed(audio, mouth, hop=8000, device="cuda"):
    rt = FalconRuntime("small", str(PROBE / "weights" / "falcon.pt")).load(device)
    out = np.zeros(len(audio), np.float32)
    n = 0
    t0 = time.perf_counter()
    for e in range(WINDOW, len(audio) + 1, hop):
        start = max(0, (e - WINDOW) // FRAME)
        frames = mouth[start:start + 50]
        if len(frames) < 50:
            break
        pred = rt.infer(audio[e - WINDOW:e], np.ascontiguousarray(frames))
        seg = pred[WINDOW - GUARD - hop:WINDOW - GUARD]
        s = e - GUARD - hop
        out[s:s + len(seg)] = seg
        n += 1
    dt = time.perf_counter() - t0
    print(f"  falcon: {n} windows, {dt:.2f}s, RTF {dt/(len(audio)/16000):.3f}")
    return out


def metrics(est, target, interf, start=2 * 16000, end_pad=3200):
    sl = slice(start, len(est) - end_pad)
    e, t = est[sl].astype(np.float64), target[sl].astype(np.float64)
    if len(e) != len(t):
        n = min(len(e), len(t))
        e, t = e[:n], t[:n]
    alpha = float(np.dot(e, t) / (np.dot(t, t) + 1e-12))
    proj = alpha * t
    si = 10 * np.log10(np.sum(proj ** 2) / (np.sum((e - proj) ** 2) + 1e-12))
    A = np.stack([target[sl][:len(e)], interf[sl][:len(e)]], 1)
    w, *_ = np.linalg.lstsq(A, e, rcond=None)
    sir = 20 * np.log10(abs(w[0]) / (abs(w[1]) + 1e-12) + 1e-12)
    corr = float(np.corrcoef(e, t)[0, 1]) if np.std(e) > 1e-12 else 0.0
    return corr, si, w[0], w[1], sir


def main():
    root = PROBE / "testrecordings"
    me, sr = sf.read(str(root / "Me-only-clear_16k.wav"), dtype="float32")
    fr, _ = sf.read(str(root / "Friend-only-clear_16k.wav"), dtype="float32")
    mouth_me = np.load(root / "Me-only-clear_mouth25.npy")
    n = min(len(me), len(fr))
    me, fr = me[:n], fr[:n]
    print(f"me rms {20*np.log10(rms(me)):.1f} dBFS, friend rms {20*np.log10(rms(fr)):.1f} dBFS, "
          f"level difference {20*np.log10(rms(fr)/rms(me)):.1f} dB")
    print(f"mouth frames {len(mouth_me)}")

    import voxlock
    from voxlock.core import loud_sample

    vl = voxlock.VoxLock(precision="int8")
    sample = loud_sample(me, sec=3.0)

    for snr in (0.0, -5.0, -10.0):
        print(f"\n=== synthetic mix, target/interferer SNR {snr:+.0f} dB ===")
        mix, scale = mix_at_snr(me, fr, snr)
        sf.write(str(root / f"eval_mix_snr{int(snr)}.wav"), mix, 16000, subtype="PCM_16")

        fout = falcon_windowed(mix, mouth_me)
        sf.write(str(root / f"eval_falcon_snr{int(snr)}.wav"), fout, 16000, subtype="PCM_16")

        t0 = time.perf_counter()
        vout = vl.isolate(mix, sample=sample)
        print(f"  voxlock: {time.perf_counter()-t0:.2f}s")
        vout = np.asarray(vout, np.float32).reshape(-1)
        sf.write(str(root / f"eval_voxlock_snr{int(snr)}.wav"), vout, 16000, subtype="PCM_16")

        for name, est in (("mixture", mix), ("VoxLock", vout), ("Falcon", fout)):
            if len(est) < len(mix):
                est = np.pad(est, (0, len(mix) - len(est)))
            corr, si, wt, wi, sir = metrics(est, me, fr)
            print(f"  {name:8s}: corr {corr:6.3f}  SI-SDR {si:7.1f} dB  "
                  f"target {wt:6.3f}  interf {wi:6.3f}  SIR {sir:6.1f} dB")

    # Real simultaneous recording with the user's own mouth.
    print("\n=== real Mixed.mp4 (no ground truth) ===")
    mixed, _ = sf.read(str(root / "Mixed_16k.wav"), dtype="float32")
    mouth_mixed = np.load(root / "Mixed_mouth25.npy")
    fout = falcon_windowed(mixed, mouth_mixed)
    sf.write(str(root / "eval_falcon_real_mixed.wav"), fout, 16000, subtype="PCM_16")
    print(f"  input rms {20*np.log10(rms(mixed)):.1f} dBFS, output rms "
          f"{20*np.log10(rms(fout)+1e-12):.1f} dBFS")


if __name__ == "__main__":
    main()
