# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Colour tokens and WCAG contrast helpers.

Values are the approved reference palette (docs/platform/02-launcher-ui.md section 8; the
mockup generator ``render.py`` uses the same hex values).
"""

C = {
    "bg": "#0B0D10",
    "surface": "#15181D",
    "surface_hover": "#1B1F25",
    "border": "#2A2F36",
    "border_muted": "#20242A",
    "divider": "#1F242B",
    "text": "#E8EAED",
    "text2": "#9AA0A6",
    "muted": "#8B949E",
    "muted_icon": "#6E7681",
    "accent": "#4CC2FF",
    "ok": "#3FB950",
    "warn": "#D29922",
    "err": "#F85149",
    "running_border": "#2F5E3A",
    "error_border": "#6B2A2A",
}


def _channel(value: int) -> float:
    c = value / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(fg: str, bg: str) -> float:
    """WCAG 2.x contrast ratio (calculated)."""
    a, b = luminance(fg), luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


# (foreground, background, minimum ratio, what it is) -- checked by tests/test_theme.py
CONTRAST_REQUIREMENTS = [
    ("text", "bg", 4.5, "primary text on background"),
    ("text", "surface", 4.5, "tile names"),
    ("text2", "bg", 4.5, "subtitle / footer secondary"),
    ("text2", "surface", 4.5, "secondary text on tiles"),
    ("muted", "surface", 4.5, "Planned / Disabled state line"),
    ("muted", "bg", 4.5, "muted text on background"),
    ("muted_icon", "surface", 3.0, "muted icons (non-text)"),
    ("accent", "bg", 3.0, "focus ring (non-text)"),
    ("accent", "surface", 3.0, "focus ring on tiles (non-text)"),
    ("ok", "surface", 4.5, "Running state line"),
    ("ok", "bg", 3.0, "connected dot (non-text)"),
    ("warn", "surface", 4.5, "Unavailable state line"),
    ("err", "surface", 4.5, "Error state line"),
    ("err", "bg", 4.5, "Core offline text"),
]


def stylesheet(scale: float = 1.0) -> str:
    """Application stylesheet for the secondary windows and dialogs (the home view paints itself)."""
    px = lambda v: f"{max(1, round(v * scale))}px"  # noqa: E731
    return f"""
QWidget {{ background: {C['bg']}; color: {C['text']}; font-size: {px(16)}; }}
QDialog, QMainWindow {{ background: {C['bg']}; }}
QLabel[role="muted"] {{ color: {C['text2']}; }}
QLabel[role="heading"] {{ font-size: {px(22)}; font-weight: 600; }}
QLabel[role="error"] {{ color: {C['err']}; }}
QLabel[role="warn"] {{ color: {C['warn']}; }}
QLabel[role="ok"] {{ color: {C['ok']}; }}
QPushButton {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: {px(8)};
  padding: {px(8)} {px(16)}; min-height: {px(32)}; }}
QPushButton:hover {{ background: {C['surface_hover']}; }}
QPushButton:focus {{ border: 2px solid {C['accent']}; }}
QPushButton:disabled {{ color: {C['muted']}; border-color: {C['border_muted']}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background: {C['surface']}; border: 1px solid {C['border']};
  border-radius: {px(6)}; padding: {px(6)}; min-height: {px(28)}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 2px solid {C['accent']}; }}
QCheckBox, QRadioButton {{ spacing: {px(8)}; }}
QTableWidget, QTreeWidget, QListWidget {{ background: {C['surface']}; alternate-background-color: #181B21;
  gridline-color: {C['border']}; border: 1px solid {C['border']}; }}
QTableWidget:focus, QTreeWidget:focus, QListWidget:focus {{ border: 2px solid {C['accent']}; }}
QHeaderView::section {{ background: {C['bg']}; color: {C['text2']}; border: none; padding: {px(6)}; }}
QGroupBox {{ border: 1px solid {C['border']}; border-radius: {px(8)}; margin-top: {px(18)}; padding: {px(10)}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: {px(10)}; color: {C['text2']}; }}
QScrollArea {{ border: none; }}
QToolTip {{ background: {C['surface']}; color: {C['text']}; border: 1px solid {C['border']}; }}
"""
