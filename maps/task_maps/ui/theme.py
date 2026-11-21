# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Dark field theme: the same colour tokens as task-launcher (task_launcher/theme.py)."""

C = {
    "bg": "#0B0D10", "surface": "#15181D", "surface_hover": "#1B1F25", "border": "#2A2F36",
    "divider": "#1F242B", "text": "#E8EAED", "text2": "#9AA0A6", "muted": "#8B949E",
    "accent": "#4CC2FF", "ok": "#3FB950", "warn": "#D29922", "err": "#F85149",
    "map_bg": "#101419", "hatch": "#3A3F47", "pending": "#4CC2FF", "track": "#FF9F43", "wpt": "#F778BA",
}


def stylesheet(compact=False) -> str:
    f = 14 if compact else 16
    pad = 6 if compact else 8
    return f"""
QWidget {{ background: {C['bg']}; color: {C['text']}; font-size: {f}px; }}
QToolBar {{ background: {C['surface']}; border-bottom: 1px solid {C['border']}; spacing: 4px; padding: 2px; }}
QToolButton {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 8px;
  padding: {pad}px {pad + 4}px; min-height: {30 if compact else 36}px; }}
QToolButton:hover {{ background: {C['surface_hover']}; }}
QToolButton:checked {{ background: #12324A; border: 1px solid {C['accent']}; }}
QToolButton:focus, QPushButton:focus {{ border: 2px solid {C['accent']}; }}
QPushButton {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 8px;
  padding: {pad}px {pad + 6}px; min-height: {30 if compact else 34}px; }}
QPushButton:hover {{ background: {C['surface_hover']}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {C['muted']}; }}
QPushButton[role="primary"] {{ background: #12324A; border: 1px solid {C['accent']}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {C['surface']}; border: 1px solid {C['border']};
  border-radius: 6px; padding: 4px 6px; min-height: {26 if compact else 30}px; }}
QListWidget, QTableWidget {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 6px; }}
QListWidget::item:selected {{ background: #12324A; }}
QProgressBar {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 6px; text-align: center;
  min-height: 20px; }}
QProgressBar::chunk {{ background: {C['accent']}; border-radius: 5px; }}
QStatusBar {{ background: {C['surface']}; border-top: 1px solid {C['border']}; color: {C['text2']}; }}
QLabel[role="muted"] {{ color: {C['text2']}; }}
QLabel[role="heading"] {{ font-size: {f + 4}px; font-weight: 600; }}
QLabel[role="warn"] {{ color: {C['warn']}; }}
QLabel[role="error"] {{ color: {C['err']}; }}
QLabel[role="ok"] {{ color: {C['ok']}; }}
QScrollArea {{ border: none; }}
QGroupBox {{ border: 1px solid {C['border']}; border-radius: 8px; margin-top: 14px; padding-top: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; color: {C['text2']}; }}
"""
