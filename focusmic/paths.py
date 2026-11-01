"""Filesystem locations for FocusMic (dev tree and packaged app)."""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "FocusMic"
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
ASSETS_DIR = PACKAGE_DIR / "assets"
VENDOR_DIR = PACKAGE_DIR / "vendor"


def _roaming() -> Path:
    return Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))


def _local() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))


def appdata_dir() -> Path:
    path = _roaming() / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def localappdata_dir() -> Path:
    path = _local() / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return appdata_dir() / "config.json"


def logs_dir() -> Path:
    path = localappdata_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_path() -> Path:
    return logs_dir() / "focusmic.log"


def mediapipe_model(name: str) -> Path:
    candidate = ASSETS_DIR / "mediapipe" / name
    if candidate.is_file():
        return candidate
    legacy = PROJECT_ROOT / "Falcon" / "studio" / "web" / "vendor" / "mediapipe" / name
    return legacy


def icon_path() -> Path:
    return ASSETS_DIR / "icons" / "focusmic_icon.ico"


def weights_dir() -> Path:
    """First existing weights directory, so dev and packaged layouts both work."""
    candidates = []
    env = os.environ.get("FOCUSMIC_WEIGHTS")
    if env:
        candidates.append(Path(env))
    candidates.extend([
        localappdata_dir() / "models",
        ASSETS_DIR / "models",
        PROJECT_ROOT / "weights",
    ])
    for path in candidates:
        if path.is_dir():
            return path
    return PROJECT_ROOT / "weights"


def weight_path(variant: str = "small") -> Path:
    name = "falcon-big.pt" if variant == "big" else "falcon.pt"
    return weights_dir() / name
