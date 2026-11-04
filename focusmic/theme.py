"""FocusMic color tokens and Qt stylesheet."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor

from .paths import ASSETS_DIR

_CHEVRON = (ASSETS_DIR / "icons" / "chevron-down.svg").as_posix()


@dataclass(frozen=True)
class Theme:
    dark: bool
    bg: str
    rail: str
    surface: str
    surface2: str
    hover: str
    border: str
    text: str
    muted: str
    faint: str
    accent: str
    accent_hover: str
    accent_soft: str
    on_accent: str
    teal: str
    red: str
    blue: str
    chart_grid: str


DARK = Theme(
    dark=True,
    bg="#0C1117",
    rail="#101720",
    surface="#151E28",
    surface2="#1A2531",
    hover="#223040",
    border="#273545",
    text="#E9EFF7",
    muted="#8B99AA",
    faint="#5E6B7A",
    accent="#F2B33D",
    accent_hover="#FFC65A",
    accent_soft="#3A2D12",
    on_accent="#1A1508",
    teal="#4FD1B0",
    red="#F07171",
    blue="#6AA8FF",
    chart_grid="#22303D",
)

LIGHT = Theme(
    dark=False,
    bg="#F2F5F8",
    rail="#FFFFFF",
    surface="#FFFFFF",
    surface2="#F7F9FC",
    hover="#EEF2F7",
    border="#DEE5ED",
    text="#17212B",
    muted="#667382",
    faint="#8C98A6",
    accent="#D99517",
    accent_hover="#C78812",
    accent_soft="#FFF1D1",
    on_accent="#211708",
    teal="#1D9C7B",
    red="#C94A4A",
    blue="#3F7FD1",
    chart_grid="#E7ECF2",
)


def theme_for(mode: str, system_dark: bool) -> Theme:
    if mode == "dark":
        return DARK
    if mode == "light":
        return LIGHT
    return DARK if system_dark else LIGHT


def stylesheet(t: Theme) -> str:
    danger_hover = QColor(t.red).lighter(112).name()
    danger_pressed = QColor(t.red).darker(112).name()
    danger_text = t.on_accent if t.dark else "#FFFFFF"
    return f"""
    QWidget {{
        color: {t.text};
        font-family: "Microsoft YaHei UI";
        font-size: 13px;
    }}
    QMainWindow, QWidget#Root {{ background: {t.bg}; }}
    QWidget#Sidebar {{ background: {t.rail}; border-right: 1px solid {t.border}; }}
    QDialog {{ background: {t.bg}; }}
    QLabel {{ background: transparent; }}
    QLabel#Muted {{ color: {t.muted}; }}
    QLabel#Faint {{ color: {t.faint}; }}
    QLabel#PageTitle {{ font-size: 26px; font-weight: 600; color: {t.text}; }}
    QLabel#PageSubtitle {{ color: {t.muted}; font-size: 12px; }}
    QLabel#CardTitle {{ font-size: 14px; font-weight: 600; color: {t.text}; }}
    QLabel#KpiValue {{ font-family: "Cascadia Mono"; font-size: 22px; font-weight: 600; color: {t.text}; }}
    QLabel#KpiLabel {{ color: {t.muted}; font-size: 11px; }}
    QFrame#Card, QWidget#Card {{
        background: {t.surface};
        border: 1px solid {t.border};
        border-radius: 12px;
    }}
    QFrame#SoftCard {{
        background: {t.surface2};
        border: 1px solid {t.border};
        border-radius: 10px;
    }}
    QFrame#RuntimeBanner {{
        background: {t.accent_soft};
        border: 1px solid {t.accent};
        border-radius: 10px;
    }}
    QComboBox, QSpinBox, QLineEdit, QKeySequenceEdit {{
        background: {t.surface2};
        border: 1px solid {t.border};
        border-radius: 7px;
        padding: 6px 9px;
        min-height: 19px;
        selection-background-color: {t.accent_soft};
        selection-color: {t.text};
    }}
    QComboBox {{ padding-right: 27px; }}
    QComboBox:hover, QSpinBox:hover, QLineEdit:hover, QKeySequenceEdit:hover {{
        border-color: {t.faint};
    }}
    QComboBox::drop-down {{ border: none; width: 25px; }}
    QComboBox::down-arrow {{
        image: url("{_CHEVRON}");
        width: 12px;
        height: 12px;
    }}
    QComboBox QAbstractItemView {{
        background: {t.surface2};
        border: 1px solid {t.border};
        border-radius: 7px;
        padding: 4px;
        selection-background-color: {t.accent_soft};
        selection-color: {t.text};
        outline: none;
    }}
    QPushButton {{
        border: 1px solid {t.border};
        border-radius: 7px;
        padding: 7px 12px;
        background: {t.surface2};
        color: {t.text};
    }}
    QPushButton:hover {{ background: {t.hover}; }}
    QPushButton:disabled {{ color: {t.faint}; background: {t.surface2}; }}
    QPushButton#primary {{
        background: {t.accent};
        border: 1px solid {t.accent};
        color: {t.on_accent};
        font-weight: 600;
        padding: 9px 16px;
    }}
    QPushButton#primary:hover {{ background: {t.accent_hover}; border-color: {t.accent_hover}; }}
    QPushButton#primary:disabled {{ background: {t.surface2}; border-color: {t.border}; color: {t.faint}; }}
    QPushButton#danger {{
        background: {t.red};
        border: 1px solid {t.red};
        color: {danger_text};
        font-weight: 600;
    }}
    QPushButton#danger:hover {{
        background: {danger_hover};
        border-color: {danger_hover};
    }}
    QPushButton#danger:pressed {{
        background: {danger_pressed};
        border-color: {danger_pressed};
    }}
    QPushButton#danger:disabled {{
        background: {t.surface2};
        border-color: {t.border};
        color: {t.faint};
    }}
    QPushButton#ghost {{ background: transparent; border-color: transparent; color: {t.muted}; }}
    QPushButton#ghost:hover {{ background: {t.hover}; color: {t.text}; }}
    QCheckBox {{ spacing: 7px; color: {t.text}; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border-radius: 5px;
        border: 1px solid {t.border}; background: {t.surface2};
    }}
    QCheckBox::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; }}
    QSlider::groove:horizontal {{ height: 4px; background: {t.border}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        width: 13px; height: 13px; margin: -5px 0; border-radius: 7px;
        background: {t.text}; border: 2px solid {t.accent};
    }}
    QPlainTextEdit, QTextBrowser {{
        background: {t.surface2};
        border: 1px solid {t.border};
        border-radius: 9px;
        padding: 8px;
        color: {t.muted};
        font-family: "Cascadia Mono", "Microsoft YaHei UI";
        font-size: 11px;
    }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 4px; min-height: 24px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QToolTip {{
        background: {t.surface2}; color: {t.text};
        border: 1px solid {t.border}; padding: 5px 7px;
    }}
    """
