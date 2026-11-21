# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Dark, field-oriented theme. Indicators are text plus an icon, never colour alone."""

from task_console.layout import Metrics

BG = "#0f1316"
SURFACE = "#182027"
SURFACE_2 = "#212b33"
BORDER = "#3a4752"
TEXT = "#e8edf1"
MUTED = "#a9b4bd"
ACCENT = "#e3a33b"
FOCUS = "#ffd479"  # contrast against BG and SURFACE well above 3:1
DANGER = "#ff8a80"
OK = "#8fd694"

ICON_CONNECTED = "\u25cf"
ICON_CONNECTING = "\u25cc"
ICON_OFFLINE = "\u2715"
ICON_WARNING = "\u26a0"
ICON_LOCK = "\U0001f512"


def stylesheet(m: Metrics) -> str:
    f = m.font_px
    t = m.target
    fw = m.focus_width
    return f"""
QWidget {{ background: {BG}; color: {TEXT}; font-size: {f}px; }}
QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-size: {m.title_font_px}px; font-weight: bold; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="mono"], QLabel[mono="true"] {{ font-family: monospace; }}
QFrame#statusStrip {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
QFrame#banner {{ background: {SURFACE_2}; border-bottom: 1px solid {BORDER}; }}
QListWidget#rail {{ background: {SURFACE}; border: none; border-right: 1px solid {BORDER}; outline: none; }}
QListWidget#rail::item {{ color: {TEXT}; border-left: 4px solid transparent; }}
QListWidget#rail::item:selected {{ background: {SURFACE_2}; border-left: 4px solid {ACCENT}; color: {TEXT}; }}
QListWidget#rail:focus {{ border: {fw}px solid {FOCUS}; }}
QPushButton {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 6px;
               min-height: {t}px; min-width: {t}px; padding: 0 {m.px(16)}px; }}
QPushButton:checked {{ background: {ACCENT}; color: {BG}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {SURFACE_2}; }}
QPushButton:focus {{ border: {fw}px solid {FOCUS}; }}
QPushButton:default {{ border: 2px solid {ACCENT}; }}
QPushButton:default:focus {{ border: {fw}px solid {FOCUS}; }}
QLineEdit {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; min-height: {t}px;
             padding: 0 {m.px(8)}px; }}
QLineEdit:focus {{ border: {fw}px solid {FOCUS}; }}
QCheckBox, QRadioButton {{ min-height: {t}px; spacing: {m.px(12)}px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: {m.px(28)}px; height: {m.px(28)}px; }}
QCheckBox:focus, QRadioButton:focus {{ border: {fw}px solid {FOCUS}; border-radius: 4px; }}
QTableView, QTableWidget {{ background: {SURFACE}; alternate-background-color: {SURFACE_2};
             gridline-color: {BORDER}; border: 1px solid {BORDER}; selection-background-color: #3d5266; }}
QTableView:focus, QTableWidget:focus {{ border: {fw}px solid {FOCUS}; }}
QHeaderView::section {{ background: {SURFACE_2}; color: {TEXT}; border: none; border-right: 1px solid {BORDER};
             min-height: {t}px; padding: 0 {m.px(8)}px; }}
QFrame#tile {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; }}
QFrame#tile:focus {{ border: {fw}px solid {FOCUS}; }}
QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; }}
QFrame#overlay {{ background: {BG}; }}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ width: {m.px(16)}px; }}
QDialog {{ background: {BG}; }}
"""
