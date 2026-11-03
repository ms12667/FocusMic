"""Windows per-user startup entry (HKCU Run)."""
from __future__ import annotations

import sys

from .paths import PROJECT_ROOT

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "FocusMic"


def _command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    launcher = PROJECT_ROOT / "FocusMic.bat"
    return f'cmd.exe /c start "" "{launcher}"'


def startup_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
        return bool(value)
    except Exception:
        return False


def set_startup(enabled: bool) -> None:
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
