"""Native Win32 tray context menu.

Qt's QMenu is drawn by Qt and looks foreign in the notification area. This
module builds a real Win32 popup menu so FocusMic inherits the system menu
font, spacing, borders and light/dark behaviour.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_GRAYED = 0x00000001

TPM_RIGHTBUTTON = 0x0002
TPM_NONOTIFY = 0x0080
TPM_RETURNCMD = 0x0100

WM_NULL = 0x0000


class _Point(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


def show_native_menu(hwnd: int, items) -> int:
    """Show a native popup at the cursor; return the chosen command id.

    ``items`` is a sequence of ``(label, enabled, command_id)`` tuples or
    ``None`` for a separator. The caller dispatches the returned id.
    """
    if not hwnd:
        return 0
    user32 = ctypes.windll.user32
    user32.CreatePopupMenu.restype = wintypes.HMENU
    user32.AppendMenuW.argtypes = [
        wintypes.HMENU, wintypes.UINT, wintypes.UINT, wintypes.LPCWSTR]
    user32.AppendMenuW.restype = wintypes.BOOL
    user32.TrackPopupMenu.argtypes = [
        wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
    user32.TrackPopupMenu.restype = ctypes.c_int
    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(_Point)]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.PostMessageW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

    menu = user32.CreatePopupMenu()
    if not menu:
        return 0
    try:
        for item in items:
            if item is None:
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                continue
            label, enabled, command = item
            flags = MF_STRING | (0 if enabled else MF_GRAYED)
            user32.AppendMenuW(menu, flags, command, label)
        point = _Point()
        if not user32.GetCursorPos(ctypes.byref(point)):
            return 0
        handle = wintypes.HWND(int(hwnd))
        # The foreground call is required for the menu to close when the user
        # clicks elsewhere, and the posted WM_NULL flushes the menu state.
        user32.SetForegroundWindow(handle)
        command = user32.TrackPopupMenu(
            menu, TPM_RIGHTBUTTON | TPM_NONOTIFY | TPM_RETURNCMD,
            point.x, point.y, 0, handle, None)
        user32.PostMessageW(handle, WM_NULL, 0, 0)
        return int(command)
    finally:
        user32.DestroyMenu(menu)
