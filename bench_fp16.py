"""Try FP16 / autocast inference for Falcon on this GPU."""
import sys
import time
from pathlib import Path

import numpy as np
import torch

PROBE = Path(__file__).resolve().parent
sys.path.insert(0, str(PROBE / "Falcon" / "studio"))
from falcon_runtime import FalconRuntime, WINDOW_FRAMES, WINDOW_SAMPLES, preprocess_mouth  # noqa: E402

rt = FalconRuntime("small", str(PROBE / "weights" / "falcon.pt")).load("cuda")
rng = np.random.default_rng(0)
audio = (rng.standard_normal(WINDOW_SAMPLES) * 0.05).astype(np.float32)
frames = rng.integers(0, 255, (WINDOW_FRAMES, 96, 96), dtype=np.uint8)
mouth = preprocess_mouth(frames).to("cuda")
wav = torch.from_numpy(audio).unsqueeze(0).to("cuda")


def bench(fn, name):
    try:
        for _ in range(5):
            fn()
        torch.cuda.synchronize()
        ts = []
        for _ in range(20):
            t0 = time.perf_counter()
            fn()
            torch.cuda.synchronize()
            ts.append((time.perf_counter() - t0) * 1000)
        t = np.array(ts)
        print(f"{name}: mean {t.mean():.2f} ms p95 {np.percentile(t,95):.2f} min {t.min():.2f}")
    except Exception as exc:  # noqa: BLE001
        print(f"{name}: FAILED {type(exc).__name__}: {str(exc).splitlines()[0][:160]}")
        torch.cuda.empty_cache()


def fp32():
    with torch.inference_mode():
        emb = rt.video_model(mouth)
        rt.audio_model(wav, emb)


def autocast():
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
        emb = rt.video_model(mouth)
        rt.audio_model(wav, emb)


bench(fp32, "fp32")
bench(autocast, "autocast fp16")

try:
    rt.video_model.half(); rt.audio_model.half()
    mouth_h, wav_h = mouth.half(), wav.half()

    def fp16():
        with torch.inference_mode():
            emb = rt.video_model(mouth_h)
            rt.audio_model(wav_h, emb)

    bench(fp16, "half weights")
except Exception as exc:  # noqa: BLE001
    print("half setup failed:", exc)
