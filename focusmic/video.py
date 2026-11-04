"""Camera + MediaPipe mouth tracking for the native FocusMic pipeline."""
from __future__ import annotations

import threading
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

from .paths import mediapipe_model

CROP = 96
FPS = 25
HAND_MODEL = mediapipe_model("hand_landmarker.task")
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
        self._resource_lock = threading.Lock()
        self._released = False
        self._stop_lock = threading.Lock()
        self._stop_called = False
        self.cap = None
        self.landmarker = None
        self.hand_landmarker = None
        self.thread = None
        self._stop = threading.Event()
        self.last_crop = None
        self.target_face = None
        self.target_width = None
        self._target_gen = 0
        self.manual_roi = None
        self.manual_pick = False
        self.manual_pick_started = 0.0
        self.manual_expired = False
        self.error = None
        self.frames_seen = 0
        self.frames_tracked = 0
        self.read_failures = 0
        self.last_time = None
        self.started_at = None
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
        self.started_at = time.perf_counter()
        return self

    def _choose_face(self, landmarks_list, width, height):
        with self.lock:
            pending = self.manual_pick
            started = self.manual_pick_started
        if pending and time.perf_counter() - started > 3.0:
            with self.lock:
                if self.manual_pick:
                    self.manual_pick = False
                    self.manual_roi = None
                    self.manual_expired = True
        faces = []
        for L in landmarks_list:
            geo = mouth_geometry(L, width, height)
            if geo is not None:
                faces.append((L, geo))
        if not faces:
            return None
        with self.lock:
            roi = self.manual_roi if self.manual_pick else None
            pick_started = self.manual_pick_started
            gen = self._target_gen
            target = self.target_face
            target_width = self.target_width
        if roi is not None and time.perf_counter() - pick_started > 3.0:
            with self.lock:
                if self._target_gen == gen:
                    self.manual_pick = False
                    self.manual_roi = None
                    self.manual_expired = True
            roi = None
        if roi is not None:
            rx0, ry0, rx1, ry1 = roi
            rcx, rcy = (rx0 + rx1) / 2.0, (ry0 + ry1) / 2.0
            inside = []
            for L, geo in faces:
                cx, cy, _side, _face_w = geo
                nx, ny = cx / max(width, 1), cy / max(height, 1)
                if rx0 <= nx <= rx1 and ry0 <= ny <= ry1:
                    inside.append((L, geo, (nx - rcx) ** 2 + (ny - rcy) ** 2))
            if not inside:
                return None
            # Prefer the face whose mouth center is nearest the middle of the
            # drawn box, not merely the largest face (the roommate may be larger).
            chosen = min(inside, key=lambda item: item[2])
            cx, cy, _side, face_w = chosen[1]
            with self.lock:
                if self._target_gen == gen:
                    self.manual_pick = False
                    self.manual_roi = None
                    self.manual_expired = False
                    self.target_face = (cx, cy, face_w)
                    self.target_width = face_w
            return chosen[0], chosen[1]
        if target is not None:
            tx, ty, tw = target
            best = None
            best_d = 1e9
            for L, geo in faces:
                cx, cy, side, face_w = geo
                shift = float(np.hypot(cx - tx, cy - ty) / max(tw, 1))
                ratio = face_w / max(target_width or face_w, 1)
                if shift <= 0.75 and 1 / 1.8 <= ratio <= 1.8 and shift < best_d:
                    best, best_d = (L, geo), shift
            if best is not None:
                cx, cy, _side, face_w = best[1]
                with self.lock:
                    if self._target_gen == gen:
                        self.target_face = (cx, cy, face_w)
                        self.target_width = face_w
                return best
            # Do not jump to another face just because the target missed one
            # frame. Keep the old target and let safe bypass handle true loss.
            return None
        chosen = max(faces, key=lambda item: item[1][3])
        cx, cy, _side, face_w = chosen[1]
        with self.lock:
            if self._target_gen == gen:
                self.target_face = (cx, cy, face_w)
                self.target_width = face_w
        return chosen

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
        try:
            while not self._stop.is_set():
                ok, frame = self.cap.read()
                if not ok:
                    self.read_failures += 1
                    time.sleep(0.02)
                    continue
                self.read_failures = 0
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
                                mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb),
                                int(now * 1000))
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
        except Exception as exc:
            self.error = f"camera thread: {exc}"
        finally:
            # The camera thread is the only owner of cap/landmarkers while it
            # runs, so it releases them here. This avoids closing MediaPipe
            # objects from the GUI thread while detect_for_video is using them.
            self._release_resources()

    def _release_resources(self):
        with self._resource_lock:
            if self._released:
                return
            self._released = True
            cap, self.cap = self.cap, None
            landmarker, self.landmarker = self.landmarker, None
            hand, self.hand_landmarker = self.hand_landmarker, None
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
        for obj in (landmarker, hand):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass

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

    def set_manual_roi(self, x0: float, y0: float, x1: float, y1: float):
        """One-shot target pick from a normalized face box on the preview."""
        with self.lock:
            self._target_gen += 1
            self.manual_roi = (
                max(0.0, min(float(x0), float(x1))),
                max(0.0, min(float(y0), float(y1))),
                min(1.0, max(float(x0), float(x1))),
                min(1.0, max(float(y0), float(y1))),
            )
            self.manual_pick = True
            self.manual_pick_started = time.perf_counter()
            self.manual_expired = False
            self.target_face = None
            self.target_width = None
            self.last_crop = None
            self.preview_box = None

    def reset_target(self):
        with self.lock:
            self._target_gen += 1
            self.target_face = None
            self.target_width = None
            self.manual_roi = None
            self.manual_pick = False
            self.manual_expired = False
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
                "manual_pick": self.manual_pick,
                "manual_expired": self.manual_expired,
                "read_failures": self.read_failures,
                "started_at": self.started_at,
                # None means start() has not been called yet.  A dead thread is
                # only meaningful after the tracker has been started.
                "thread_alive": (
                    None if self.thread is None else bool(self.thread.is_alive())),
                "last_time": self.last_time,
                "error": self.error,
            }

    def stop(self):
        with self._stop_lock:
            if self._stop_called:
                return
            self._stop_called = True
        self._stop.set()
        thread = self.thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            # A blocking cap.read() or detect_for_video() can take a moment.
            # Never close MediaPipe objects while that thread is still inside
            # them: the camera thread's finally block owns resource release.
            thread.join(timeout=2.0)
        if thread is None or not thread.is_alive():
            self._release_resources()


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
