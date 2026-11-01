"""Extract 96x96 grayscale mouth crops from a video, following Falcon Studio's geometry."""
import sys
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

PROBE = Path(__file__).resolve().parent
VIDEO = Path(sys.argv[1]) if len(sys.argv) > 1 else PROBE / "demo" / "small_s1.mp4"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else PROBE / "demo" / "small_mouth.npy"
MODEL = PROBE / "Falcon" / "studio" / "web" / "vendor" / "mediapipe" / "face_landmarker.task"
CROP = 96

options = vision.FaceLandmarkerOptions(
    base_options=python.BaseOptions(model_asset_path=str(MODEL)),
    running_mode=vision.RunningMode.VIDEO,
    num_faces=1,
    min_face_detection_confidence=0.5,
    min_face_presence_confidence=0.5,
    min_tracking_confidence=0.5,
)
landmarker = vision.FaceLandmarker.create_from_options(options)

cap = cv2.VideoCapture(str(VIDEO))
fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
print(f"video {VIDEO.name}: {total} frames @ {fps:.2f} fps")

crops = []
last = None
idx = 0
while True:
    ok, frame = cap.read()
    if not ok:
        break
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (540, 960), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    result = landmarker.detect_for_video(
        mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), int(idx * 1000 / fps))

    if result.face_landmarks:
        L = result.face_landmarks[0]
        left, right = L[61], L[291]
        fl, fr = L[234], L[454]
        cx = (left.x + right.x) / 2 * w
        cy = (left.y + right.y) / 2 * h
        face_w = np.hypot((fl.x - fr.x) * w, (fl.y - fr.y) * h)
        mouth_w = np.hypot((left.x - right.x) * w, (left.y - right.y) * h)
        if face_w > 20 and mouth_w > 4:
            scale = np.clip(2.13 * mouth_w / face_w, 0.45, 1.1)
            side = max(32, int(face_w * scale))
            x0, y0 = int(cx - side / 2), int(cy - side / 2)
            x1, y1 = x0 + side, y0 + side
            canvas = np.zeros((side, side, 3), np.uint8)
            sx0, sy0 = max(0, x0), max(0, y0)
            sx1, sy1 = min(w, x1), min(h, y1)
            if sx1 > sx0 and sy1 > sy0:
                canvas[sy0 - y0: sy1 - y0, sx0 - x0: sx1 - x0] = frame[sy0:sy1, sx0:sx1]
            last = cv2.resize(cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY), (CROP, CROP))
    crops.append(last if last is not None else np.zeros((CROP, CROP), np.uint8))
    idx += 1
    if idx % 250 == 0:
        print(f"  {idx}/{total}", flush=True)

cap.release()
landmarker.close()
arr = np.stack(crops)
np.save(OUT, arr)
cv2.imwrite(str(OUT.with_name(OUT.stem + "_first.png")), arr[0])
print(f"saved {OUT} shape {arr.shape} dtype {arr.dtype}")
