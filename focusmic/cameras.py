"""Camera descriptions for the device pickers.

OpenCV only exposes integer camera indices, so the old UI showed a blind
“Camera 0–5” list.  Qt Multimedia can query the Windows camera list (names and
supported formats) without opening a camera, which lets us show a useful label
before the user starts separation.  The Qt/OpenCV index order follows the same
OS enumeration order in practice; if Qt is unavailable we fall back to the
generic indices.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CameraInfo:
    index: int
    name: str = ""
    width: int = 0
    height: int = 0
    fps: float = 0.0

    def label(self, fallback: str) -> str:
        parts = [self.name or fallback]
        if self.width > 0 and self.height > 0:
            parts.append(f"{self.width}×{self.height}")
        if self.fps > 0:
            parts.append(f"{self.fps:g} fps")
        return "  ·  ".join(parts)


def _best_format(formats) -> tuple[int, int, float]:
    """Pick a useful capture format, preferring 720p then 1080p."""
    values: set[tuple[int, int, float]] = set()
    for fmt in formats:
        try:
            size = fmt.resolution()
            width, height = int(size.width()), int(size.height())
            fps = max(float(fmt.minFrameRate()), float(fmt.maxFrameRate()))
        except Exception:
            continue
        if width > 0 and height > 0:
            values.add((width, height, round(fps, 1)))
    if not values:
        return 0, 0, 0.0
    for width, height in ((1280, 720), (1920, 1080)):
        matches = [value for value in values
                   if value[0] == width and value[1] == height]
        if matches:
            return max(matches, key=lambda value: value[2])
    under_hd = [value for value in values
                if value[0] * value[1] <= 1920 * 1080]
    if under_hd:
        return max(under_hd, key=lambda value: (value[0] * value[1], value[2]))
    return min(values, key=lambda value: value[0] * value[1])


def list_cameras(max_index: int = 6) -> list[CameraInfo]:
    """Return cameras without opening them; falls back to generic indices."""
    try:
        from PySide6.QtMultimedia import QMediaDevices

        devices = list(QMediaDevices.videoInputs())
    except Exception:
        devices = []
    infos: list[CameraInfo] = []
    for index, device in enumerate(devices[:max_index]):
        try:
            name = str(device.description() or "").strip()
        except Exception:
            name = ""
        try:
            width, height, fps = _best_format(device.videoFormats())
        except Exception:
            width, height, fps = 0, 0, 0.0
        infos.append(CameraInfo(index, name, width, height, fps))
    if infos:
        return infos
    return [CameraInfo(index) for index in range(max_index)]
