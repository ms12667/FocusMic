"""Offline packaged-build self-test. Never opens the microphone or camera."""
from __future__ import annotations

import json
import platform
import traceback

import numpy as np
from pathlib import Path

from .paths import ASSETS_DIR, log_path, weight_path


def run_selftest() -> int:
    report = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "assets": str(ASSETS_DIR),
        "ok": False,
    }
    try:
        import cv2
        import mediapipe
        from .runtime import ensure_runtime

        status = ensure_runtime(check_cuda=True)
        if not status.ok:
            raise RuntimeError(status.message())
        import torch
        from .vendor.falcon.falcon_runtime import FalconRuntime, WINDOW_SAMPLES

        report.update({
            "runtime_root": str(status.root),
            "torch": torch.__version__,
            "cuda_build": torch.version.cuda,
            "cuda_available": bool(torch.cuda.is_available()),
            "mediapipe": mediapipe.__version__,
            "opencv": cv2.__version__,
            "face_model": str(ASSETS_DIR / "mediapipe" / "face_landmarker.task"),
            "hand_model": str(ASSETS_DIR / "mediapipe" / "hand_landmarker.task"),
            "small_weights": str(weight_path("small")),
            "big_weights": str(weight_path("big")),
        })
        for key in ("face_model", "hand_model", "small_weights", "big_weights"):
            report[key + "_exists"] = Path(report[key]).is_file()
        runtime = FalconRuntime("small", str(weight_path("small"))).load("cuda")
        pred = runtime.infer(
            np.zeros(WINDOW_SAMPLES, dtype=np.float32),
            np.full((50, 96, 96), 107, dtype=np.uint8),
        )
        report.update({
            "device": runtime.device,
            "warmup_ms": runtime.warmup_ms,
            "infer_ms": runtime.last_inference_ms,
            "output_shape": list(pred.shape),
            "parameters": runtime.parameter_count,
            "ok": True,
        })
    except Exception:
        report["error"] = traceback.format_exc()
    target = log_path().with_name("selftest.log")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
