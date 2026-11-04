"""Persistent user settings in %APPDATA%\\FocusMic\\config.json."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .paths import config_path


@dataclass
class Settings:
    mic_name: str = ""
    mic_hostapi: str = ""
    close_to_tray: bool = True
    camera: int = 0
    variant: str = "small"
    av_offset_ms: int = 30
    monitor: bool = False
    gain_db: float = 6.0
    window_width: int = 1080
    window_height: int = 810
    theme_mode: str = "system"  # system | dark | light
    hotkey_enabled: bool = True
    hotkey: str = "ctrl+alt+m"
    start_with_windows: bool = False
    onboarding_done: bool = False


def _coerce(data: dict) -> Settings:
    defaults = Settings()
    out = Settings()
    out.mic_name = str(data.get("mic_name", defaults.mic_name) or "")
    out.mic_hostapi = str(data.get("mic_hostapi", defaults.mic_hostapi) or "")
    out.close_to_tray = bool(data.get("close_to_tray", defaults.close_to_tray))
    try:
        out.camera = max(0, int(data.get("camera", defaults.camera)))
    except (TypeError, ValueError):
        out.camera = defaults.camera
    out.variant = "big" if data.get("variant") == "big" else "small"
    try:
        out.av_offset_ms = max(-250, min(250, int(data.get("av_offset_ms", defaults.av_offset_ms))))
    except (TypeError, ValueError):
        out.av_offset_ms = defaults.av_offset_ms
    out.monitor = bool(data.get("monitor", defaults.monitor))
    try:
        out.gain_db = max(-12.0, min(12.0, float(data.get("gain_db", defaults.gain_db))))
    except (TypeError, ValueError):
        out.gain_db = defaults.gain_db
    try:
        out.window_width = max(960, int(data.get("window_width", defaults.window_width)))
        out.window_height = max(720, int(data.get("window_height", defaults.window_height)))
    except (TypeError, ValueError):
        out.window_width, out.window_height = defaults.window_width, defaults.window_height
    mode = data.get("theme_mode", defaults.theme_mode)
    out.theme_mode = mode if mode in ("system", "dark", "light") else defaults.theme_mode
    out.hotkey_enabled = bool(data.get("hotkey_enabled", defaults.hotkey_enabled))
    hotkey = str(data.get("hotkey", defaults.hotkey) or defaults.hotkey).strip().lower()
    out.hotkey = hotkey or defaults.hotkey
    out.start_with_windows = bool(data.get("start_with_windows", defaults.start_with_windows))
    # Existing configs predate the wizard; only a brand-new install sees it.
    out.onboarding_done = bool(data.get("onboarding_done", True))
    return out


def load_settings(path: Path | None = None) -> Settings:
    target = path or config_path()
    try:
        with target.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return _coerce(data)
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError):
        pass
    return Settings()


def save_settings(settings: Settings, path: Path | None = None) -> None:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(asdict(settings), handle, ensure_ascii=False, indent=2)
    tmp.replace(target)
