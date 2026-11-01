"""Camera + MediaPipe mouth tracking for the native FocusMic pipeline."""
from __future__ import annotations

import threading
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

CROP = 96
FPS = 25
HAND_MODEL = Path(__file__).resolve().parent.parent / "Falcon" / "studio" / "web" / "vendor" / "mediapipe" / "hand_landmarker.task"
OUTER_LIP_INDICES = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375,
                     291, 409, 270, 269, 267, 0, 37, 39, 40, 185]


def mouth_geometry(landmarks, width: int, height: int):
    try:
        left, right = landmarks[61], landmarks[291]
        fl, fr = landmarks[234], landmarks[454]
    except IndexError:
        return None
    face_w = float(np.hypot((fl.x - fr.x) * width, (fl.y - fr.y) * height))
    mouth_w = float(np.hypot((left.x - right.x) * width, (left.y - right.y) * height))
    if face_w < 20 or mouth_w < 4 or mouth_w > face_w * 0.85:
        return None
    cx = (left.x + right.x) / 2 * width
    cy = (left.y + right.y) / 2 * height
    scale = float(np.clip(2.13 * mouth_w / face_w, 0.45, 1.1))
    return cx, cy, face_w * scale, face_w


def lip_box(landmarks, width: int, height: int, margin: float = 0.25):
    """Tight box around the lips, not the large nose/chin crop."""
    pts = []
    for i in (61, 291, 0, 17, 13, 14):
        try:
            pts.append((landmarks[i].x * width, landmarks[i].y * height))
        except IndexError:
            return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    dx, dy = (x1 - x0) * margin, (y1 - y0) * margin
    return x0 - dx, y0 - dy, x1 + dx, y1 + dy


def crop_mouth(frame: np.ndarray, landmarks) -> np.ndarray | None:
    h, w = frame.shape[:2]
    geo = mouth_geometry(landmarks, w, h)
    if geo is None:
        return None
    cx, cy, side, _ = geo
    side = max(32, int(round(side)))
    x0, y0 = int(round(cx - side / 2)), int(round(cy - side / 2))
    canvas = np.zeros((side, side, 3), np.uint8)
    sx0, sy0 = max(0, x0), max(0, y0)
    sx1, sy1 = min(w, x0 + side), min(h, y0 + side)
    if sx1 > sx0 and sy1 > sy0:
        canvas[sy0 - y0: sy1 - y0, sx0 - x0: sx1 - x0] = frame[sy0:sy1, sx0:sx1]
    return cv2.resize(cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY), (CROP, CROP),
                      interpolation=cv2.INTER_AREA)


class MouthTracker:
    """One camera thread; auto-locks the largest/nearest consistent face."""

    def __init__(self, camera: int = 0, width: int = 1280, height: int = 720,
                 fps: int = FPS, model_path: str | Path | None = None,
                 hand_model_path: str | Path | None = None):
        self.camera = int(camera)
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.model_path = Path(model_path) if model_path else None
        self.hand_model_path = Path(hand_model_path) if hand_model_path else HAND_MODEL
        self.frames = deque(maxlen=int(fps * 8))
        self.lock = threading.Lock()
        self.cap = None
        self.landmarker = None
        self.hand_landmarker = None
        self.thread = None
        self._stop = threading.Event()
        self.last_crop = None
        self.target_face = None
        self.target_width = None
        self.error = None
        self.frames_seen = 0
        self.frames_tracked = 0
        self.last_time = None
        self.preview = None
        self.preview_box = None
        self.occlusion_streak = 0
        self.occluded = False

    def start(self):
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
        self.cap = cv2.VideoCapture(self.camera, cv2.CAP_MSMF)
        if not self.cap.isOpened():
            self.cap.release()
            self.cap = cv2.VideoCapture(self.camera)
        if not self.cap.isOpened():
            raise RuntimeError(f"无法打开摄像头 {self.camera}。")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if self.model_path is None or not self.model_path.is_file():
            raise RuntimeError("找不到 MediaPipe face_landmarker.task。")
        options = vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(self.model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=2,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self.landmarker = vision.FaceLandmarker.create_from_options(options)
        if self.hand_model_path.is_file():
            hand_options = vision.HandLandmarkerOptions(
                base_options=python.BaseOptions(model_asset_path=str(self.hand_model_path)),
                running_mode=vision.RunningMode.VIDEO,
                num_hands=2,
                min_hand_detection_confidence=0.5,
                min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self.hand_landmarker = vision.HandLandmarker.create_from_options(hand_options)
        else:
            self.hand_landmarker = None
        self.thread = threading.Thread(target=self._run, daemon=True, name="mouth-tracker")
        self.thread.start()
        return self

    def _choose_face(self, landmarks_list, width, height):
        faces = []
        for L in landmarks_list:
            geo = mouth_geometry(L, width, height)
            if geo is not None:
                faces.append((L, geo))
        if not faces:
            return None
        if self.target_face is not None:
            tx, ty, tw = self.target_face
            best = None
            best_d = 1e9
            for L, geo in faces:
                cx, cy, side, face_w = geo
                shift = float(np.hypot(cx - tx, cy - ty) / max(tw, 1))
                ratio = face_w / max(self.target_width or face_w, 1)
                if shift <= 0.75 and 1 / 1.8 <= ratio <= 1.8 and shift < best_d:
                    best, best_d = (L, geo), shift
            if best is not None:
                return best
        return max(faces, key=lambda item: item[1][3])

    @staticmethod
    def _hand_covers_mouth(hand_result, box, w, h) -> bool:
        if hand_result is None or not getattr(hand_result, "hand_landmarks", None):
            return False
        if box is None:
            return False
        x0, y0, x1, y1 = box
        area = max(1.0, (x1 - x0) * (y1 - y0))
        for hand in hand_result.hand_landmarks:
            if len(hand) < 21:
                continue
            inside = 0
            xs, ys = [], []
            for p in hand:
                px, py = p.x * w, p.y * h
                xs.append(px)
                ys.append(py)
                if x0 <= px <= x1 and y0 <= py <= y1:
                    inside += 1
            # Require several actual hand landmarks inside the *lip* box, or a
            # hand whose bounding box covers most of that box and whose palm
            # sits over it. A hand merely near the large green crop no longer
            # counts as occlusion.
            palm = hand[9]
            px, py = palm.x * w, palm.y * h
            overlap = max(0.0, min(x1, max(xs)) - max(x0, min(xs))) * \
                      max(0.0, min(y1, max(ys)) - max(y0, min(ys)))
            if inside >= 3:
                return True
            if overlap / area >= 0.45 and x0 <= px <= x1 and y0 <= py <= y1:
                return True
        return False

    def _run(self):
        from mediapipe.tasks.python import vision  # noqa: F401  (runtime import already done)
        while not self._stop.is_set():
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.02)
                continue
            now = time.perf_counter()
            h, w = frame.shape[:2]
            scale = min(1.0, 960.0 / max(w, h))
            small = cv2.resize(frame, (int(round(w * scale)), int(round(h * scale))),
                               interpolation=cv2.INTER_AREA)
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            import mediapipe as mp
            result = self.landmarker.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), int(now * 1000))
            chosen = self._choose_face(result.face_landmarks or [], w, h)
            crop = None
            tracked = False
            if chosen is not None:
                L, geo = chosen
                cx, cy, side, face_w = geo
                raw_occluded = False
                if self.hand_landmarker is not None:
                    try:
                        hand_result = self.hand_landmarker.detect_for_video(
                            mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), int(now * 1000))
                        raw_occluded = self._hand_covers_mouth(
                            hand_result, lip_box(L, w, h), w, h)
                    except Exception as exc:
                        self.error = f"hand tracker: {exc}"
                        self.hand_landmarker = None
                self.occlusion_streak = self.occlusion_streak + 1 if raw_occluded else 0
                occluded = self.occlusion_streak >= 3
                self.occluded = occluded
                if not occluded:
                    crop = crop_mouth(frame, L)
                    if crop is not None:
                        tracked = True
                        self.target_face = (cx, cy, face_w)
                        self.target_width = face_w
                        self.last_crop = crop
                        self.preview_box = (cx / w, cy / h, side / min(w, h))
                else:
                    crop = self.last_crop
                    self.preview_box = (cx / w, cy / h, side / min(w, h))
            else:
                self.occlusion_streak = 0
                self.occluded = False
            if crop is None:
                crop = self.last_crop if self.last_crop is not None else np.zeros((CROP, CROP), np.uint8)
            with self.lock:
                self.frames.append((now, crop, tracked))
                self.frames_seen += 1
                if tracked:
                    self.frames_tracked += 1
                self.last_time = now
                self.preview = cv2.resize(frame, (640, 360), interpolation=cv2.INTER_AREA)
            # Keep the camera at ~25 fps even if the driver runs faster.
            time.sleep(max(0.0, 1.0 / self.fps - (time.perf_counter() - now)))

    def frames_for(self, start_time: float, end_time: float, count: int = 50,
                   offset_ms: float = 30.0) -> tuple[np.ndarray, float]:
        times = start_time + offset_ms / 1000.0 + (np.arange(count) + 0.5) / FPS
        out = np.zeros((count, CROP, CROP), np.uint8)
        tracked = 0
        with self.lock:
            frames = list(self.frames)
        if not frames:
            return out, 0.0
        stamps = np.array([f[0] for f in frames])
        for i, t in enumerate(times):
            j = int(np.searchsorted(stamps, t))
            j = min(max(j, 0), len(frames) - 1)
            if j > 0 and abs(stamps[j - 1] - t) < abs(stamps[j] - t):
                j -= 1
            out[i] = frames[j][1]
            if frames[j][2] and abs(stamps[j] - t) <= 0.2:
                tracked += 1
        return out, tracked / count

    def reset_target(self):
        with self.lock:
            self.target_face = None
            self.target_width = None
            self.last_crop = None
            self.preview_box = None

    def preview_frame(self):
        with self.lock:
            frame = None if self.preview is None else self.preview.copy()
            box = self.preview_box
        return frame, box

    def status(self) -> dict:
        with self.lock:
            return {
                "frames": len(self.frames),
                "seen": self.frames_seen,
                "tracked": self.frames_tracked,
                "fps": (self.frames_tracked / max(1, self.frames_seen)),
                "occluded": self.occluded,
                "error": self.error,
            }

    def stop(self):
        self._stop.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        if self.landmarker is not None:
            self.landmarker.close()
            self.landmarker = None
        if self.hand_landmarker is not None:
            self.hand_landmarker.close()
            self.hand_landmarker = None


class SimMouth:
    """File-backed 25 fps mouth source for pipeline tests."""

    def __init__(self, npy_path: str | Path, fps: int = FPS):
        self.mouth = np.load(str(npy_path))
        self.fps = int(fps)
        self.start_time = None
        self.last_crop = None
        self.frames_seen = 0

    def start(self):
        self.start_time = time.perf_counter()
        return self

    def align_to(self, t0: float):
        self.start_time = float(t0)

    def frames_for(self, start_time: float, end_time: float, count: int = 50,
                   offset_ms: float = 30.0) -> tuple[np.ndarray, float]:
        t0 = self.start_time or time.perf_counter()
        times = start_time + offset_ms / 1000.0 + (np.arange(count) + 0.5) / self.fps
        idx = np.rint((times - t0) * self.fps).astype(int)
        idx = np.clip(idx, 0, len(self.mouth) - 1)
        out = self.mouth[idx].astype(np.uint8, copy=False)
        return out, 1.0

    def status(self) -> dict:
        return {"frames": len(self.mouth), "seen": len(self.mouth), "tracked": 1.0, "fps": 1.0}

    def stop(self):
        pass
