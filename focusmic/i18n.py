"""Small JSON-backed translation catalog for FocusMic.

The application ships one catalog per language under ``focusmic/locales``.
Keys are stable identifiers (``nav.home``); missing entries fall back to
English and then Simplified Chinese, so a partially translated catalog never
shows a raw key in the UI.

This module deliberately has no Qt import at module level: the CLI and the
runtime checks can call :func:`t` without starting a QApplication.  System
language detection uses Qt when available and the C locale otherwise.
"""
from __future__ import annotations

import json
import locale
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_LANGUAGE = "en"
SOURCE_LANGUAGE = "zh_CN"
AUTO_LANGUAGE = "auto"


@dataclass(frozen=True)
class Language:
    code: str
    native: str
    english: str
    qt_tag: str


LANGUAGES: tuple[Language, ...] = (
    Language("zh_CN", "简体中文", "Chinese (Simplified)", "zh-Hans"),
    Language("zh_TW", "繁體中文", "Chinese (Traditional)", "zh-Hant"),
    Language("en", "English", "English", "en"),
    Language("ja", "日本語", "Japanese", "ja"),
    Language("ko", "한국어", "Korean", "ko"),
    Language("es", "Español", "Spanish", "es"),
    Language("fr", "Français", "French", "fr"),
    Language("de", "Deutsch", "German", "de"),
    Language("pt_BR", "Português (Brasil)", "Portuguese (Brazil)", "pt-BR"),
    Language("ru", "Русский", "Russian", "ru"),
)

_BY_CODE = {language.code: language for language in LANGUAGES}
_ALIASES = {
    "zh": "zh_CN",
    "zh_cn": "zh_CN",
    "zh_hans": "zh_CN",
    "zh_sg": "zh_CN",
    "zh_tw": "zh_TW",
    "zh_hk": "zh_TW",
    "zh_mo": "zh_TW",
    "zh_hant": "zh_TW",
    "en_us": "en",
    "en_gb": "en",
    "ja_jp": "ja",
    "ko_kr": "ko",
    "es_es": "es",
    "es_mx": "es",
    "fr_fr": "fr",
    "fr_ca": "fr",
    "de_de": "de",
    "de_at": "de",
    "pt": "pt_BR",
    "pt_br": "pt_BR",
    "pt_pt": "pt_BR",
    "ru_ru": "ru",
}

_current = DEFAULT_LANGUAGE
_catalogs: dict[str, dict[str, str]] = {}


def locales_dir() -> Path:
    """Catalog directory in a source checkout or a PyInstaller bundle."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "focusmic" / "locales"
    return Path(__file__).resolve().parent / "locales"


def normalize(code: str | None) -> str:
    """Map a locale-ish string (``zh-CN``, ``pt_BR``) to a catalog code."""
    raw = str(code or "").strip().replace("-", "_").lower()
    if not raw or raw == AUTO_LANGUAGE:
        return ""
    if raw in _ALIASES:
        return _ALIASES[raw]
    if raw in _BY_CODE:
        return raw
    base = raw.split("_", 1)[0]
    if base in _BY_CODE:
        return base
    if base == "zh":
        return "zh_TW" if raw.startswith("zh_tw") else "zh_CN"
    return ""


def detect_system_language() -> str:
    """Best-effort match of the Windows/UI language to a shipped catalog."""
    name = ""
    try:
        from PySide6.QtCore import QLocale  # imported lazily for CLI use

        name = QLocale.system().name()
    except Exception:
        try:
            name = locale.getlocale()[0] or ""
        except Exception:
            name = ""
    return normalize(name) or DEFAULT_LANGUAGE


def resolve_language(code: str | None) -> str:
    """Resolve ``auto`` (or an invalid value) to a concrete catalog code."""
    if str(code or "").strip().lower() == AUTO_LANGUAGE:
        return detect_system_language()
    return normalize(code) or detect_system_language()


def language_info(code: str) -> Language:
    return _BY_CODE.get(resolve_language(code), _BY_CODE[DEFAULT_LANGUAGE])


def language_name(code: str | None = None, native: bool = True) -> str:
    info = language_info(_current if code is None else code)
    return info.native if native else info.english


def _load(code: str) -> dict[str, str]:
    if code in _catalogs:
        return _catalogs[code]
    path = locales_dir() / f"{code}.json"
    data: dict[str, str] = {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if isinstance(raw, dict):
            data = {str(key): str(value) for key, value in raw.items()
                    if isinstance(value, str)}
    except (OSError, ValueError, TypeError):
        data = {}
    _catalogs[code] = data
    return data


def set_language(code: str | None) -> str:
    """Activate a catalog; returns the concrete code that was selected."""
    global _current
    selected = resolve_language(code)
    if selected not in _BY_CODE:
        selected = DEFAULT_LANGUAGE
    _load(selected)
    _current = selected
    return selected


def current_language() -> str:
    return _current


def t(key: str, **kwargs) -> str:
    """Translate ``key``; unknown keys return the key itself."""
    value = _load(_current).get(key)
    if value is None:
        for fallback in (DEFAULT_LANGUAGE, SOURCE_LANGUAGE):
            value = _load(fallback).get(key)
            if value is not None:
                break
    if value is None:
        return key
    if kwargs:
        try:
            return value.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return value
    return value


def missing_keys(code: str, reference: str = DEFAULT_LANGUAGE) -> list[str]:
    """Keys present in ``reference`` but absent from ``code`` (for tests)."""
    expected = set(_load(reference))
    actual = set(_load(code))
    return sorted(expected - actual)


def ui_font_family() -> str:
    """A family with good coverage for the current UI language."""
    if _current == "ja":
        return "Yu Gothic UI"
    if _current == "ko":
        return "Malgun Gothic"
    if _current == "zh_TW":
        return "Microsoft JhengHei UI"
    if _current == "zh_CN":
        return "Microsoft YaHei UI"
    return "Segoe UI"
