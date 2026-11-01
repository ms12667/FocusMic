"""Prepare OBS recordings: 16 kHz mono audio + 25 fps 96x96 mouth crops.

Usage:
    python prep_recordings.py [recordings_dir]

Writes <stem>_16k.wav, <stem>_mouth25.npy (T,96,96 uint8), <stem>_mouth25_times.npy,
<stem>_mouth25_detected.npy and <stem>_mouth25_sheet.png next to each source.
"""
from __future__ import annotations

import sys
from pathlib import Path

import av
import cv2
import mediapipe as mp
import numpy as np
import soundfile as sf
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

PROBE = Path(__file__).resolve().parent
MODEL = PROBE / "Falcon" / "studio" / "web" / "vendor" / "mediapipe" / "face_landmarker.task"
CROP = 96
TARGET_FPS = 25.0


def decode_audio(path: Path, out_wav: Path) -> tuple[np.ndarray, float]:
    container = av.open(str(path))
    stream = container.streams.audio[0]
    first_pts = None
    resampler = av.AudioResampler(format="flt", layout="mono", rate=16000)
    chunks: list[np.ndarray] = []
    for frame in container.decode(stream):
        if first_pts is None:
            first_pts = float(frame.pts * stream.time_base) if frame.pts is not None else 0.0
        for resampled in resampler.resample(frame):
            chunks.append(resampled.to_ndarray().reshape(-1).astype(np.float32, copy=False))
    for resampled in resampler.resample(None):
        chunks.append(resampled.to_ndarray().reshape(-1).astype(np.float32, copy=False))
    container.close()
    audio = np.concatenate(chunks) if chunks else np.zeros(0, np.float32)
    sf.write(str(out_wav), audio, 16000, subtype="PCM_16")
    start = first_pts or 0.0
    rms = float(np.sqrt(np.mean(audio**2))) if len(audio) else 0.0
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    print(f"  audio: {len(audio)/16000:.3f}s  start={start:.4f}s  "
          f"rms={20*np.log10(rms+1e-12):.1f} dBFS  peak={20*np.log10(peak+1e-12):.1f} dBFS")
    return audio, start


def mouth_geometry(landmarks, width: int, height: int):
    # Falcon Studio geometry: mouth corners 61/291, face width 234/454.
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
    return cx, cy, face_w * scale, scale


def crop_mouth(frame, landmarks):
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


def decode_mouth(path: Path, out_npy: Path, out_times: Path, out_det: Path, out_sheet: Path):
    options = vision.FaceLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=str(MODEL)),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=2,
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    landmarker = vision.FaceLandmarker.create_from_options(options)
    container = av.open(str(path))
    stream = container.streams.video[0]
    frames: list[np.ndarray] = []
    times: list[float] = []
    detected: list[bool] = []
    last = None
    count = 0
    for frame in container.decode(stream):
        if frame.pts is None:
            continue
        t = float(frame.pts * stream.time_base)
        img = frame.to_ndarray(format="bgr24")
        h, w = img.shape[:2]
        # Preserve aspect ratio; cap the long side at 960 px for MediaPipe.
        scale = min(1.0, 960.0 / max(w, h))
        small = cv2.resize(img, (int(round(w * scale)), int(round(h * scale))),
                           interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        result = landmarker.detect_for_video(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), int(round(t * 1000)))
        crop = None
        if result.face_landmarks:
            # Pick the largest detected face; the target is normally the closest/largest.
            best = None
            best_w = -1.0
            for L in result.face_landmarks:
                geo = mouth_geometry(L, w, h)
                if geo is not None and geo[2] > best_w:
                    best, best_w = L, geo[2]
            if best is not None:
                crop = crop_mouth(img, best)
        if crop is not None:
            last = crop
            detected.append(True)
        else:
            detected.append(False)
        frames.append(last if last is not None else np.zeros((CROP, CROP), np.uint8))
        times.append(t)
        count += 1
        if count % 200 == 0:
            print(f"  video {count} frames...", flush=True)
    container.close()
    landmarker.close()

    times_arr = np.asarray(times, np.float64)
    frames_arr = np.stack(frames)
    # Resample to exactly 25 fps on a uniform grid starting at the first video frame.
    if len(times_arr) == 0:
        raise RuntimeError(f"no video frames in {path}")
    t0 = times_arr[0]
    duration = times_arr[-1] - t0
    grid = np.arange(0.0, duration + 1e-6, 1.0 / TARGET_FPS)
    idx = np.searchsorted(times_arr - t0, grid)
    idx = np.clip(idx, 0, len(frames_arr) - 1)
    # Choose the nearer of the two bracketing frames.
    prev = np.clip(idx - 1, 0, len(frames_arr) - 1)
    choose_prev = np.abs((times_arr - t0)[prev] - grid) < np.abs((times_arr - t0)[idx] - grid)
    idx = np.where(choose_prev, prev, idx)
    mouth = frames_arr[idx]
    det = np.asarray(detected, bool)[idx]
    np.save(out_npy, mouth)
    np.save(out_times, grid + t0)
    np.save(out_det, det)

    # Contact sheet for a quick visual check (12 crops across, 3 rows).
    cols, rows = 12, 3
    step = max(1, len(mouth) // (cols * rows))
    picks = mouth[::step][: cols * rows]
    sheet = np.zeros((rows * CROP, cols * CROP), np.uint8)
    for i, crop in enumerate(picks):
        r, c = divmod(i, cols)
        sheet[r * CROP:(r + 1) * CROP, c * CROP:(c + 1) * CROP] = crop
    cv2.imwrite(str(out_sheet), sheet)
    print(f"  video: {count} frames, {duration:.3f}s, 25fps grid {len(mouth)} frames, "
          f"detected {det.mean()*100:.1f}%, saved {out_npy.name}")


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else PROBE / "testrecordings"
    files = sorted(p for p in root.glob("*.mp4") if p.is_file())
    if not files:
        raise SystemExit(f"no .mp4 in {root}")
    for path in files:
        print(f"\n== {path.name} ==")
        stem = path.with_suffix("")
        decode_audio(path, stem.with_name(stem.name + "_16k.wav"))
        decode_mouth(path,
                     stem.with_name(stem.name + "_mouth25.npy"),
                     stem.with_name(stem.name + "_mouth25_times.npy"),
                     stem.with_name(stem.name + "_mouth25_detected.npy"),
                     stem.with_name(stem.name + "_mouth25_sheet.png"))


if __name__ == "__main__":
    main()
