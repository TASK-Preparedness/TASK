# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Original dark "field" theme and touch metrics (no third-party assets or colours copied)."""

from __future__ import annotations

from dataclasses import dataclass

BG = "#101418"
PANEL = "#1a2026"
PANEL_2 = "#222a32"
BORDER = "#2e3842"
TEXT = "#d8dee4"
TEXT_DIM = "#8a96a3"
AMBER = "#f2a900"
GREEN = "#3ccf6e"
RED = "#e5484d"
BLUE = "#4aa3df"
STALE = "#7c8793"


@dataclass(frozen=True)
class Metrics:
    name: str
    target: int      # minimum interactive target, logical px
    row: int         # table row height
    font_pt: int
    badge_pt: int


TOUCH = Metrics("touch", target=48, row=44, font_pt=11, badge_pt=20)
COMPACT = Metrics("compact", target=32, row=28, font_pt=10, badge_pt=16)


def metrics_for(density: str, screen_logical_height: int) -> Metrics:
    if density == "touch":
        return TOUCH
    if density == "compact":
        return COMPACT
    return COMPACT if screen_logical_height >= 900 else TOUCH


BADGE_COLOURS = {"CONNECTED": GREEN, "CONNECTING…": AMBER, "DISCONNECTED": RED}


def stylesheet(m: Metrics) -> str:
    return f"""
    QWidget {{ background: {BG}; color: {TEXT}; font-size: {m.font_pt}pt; }}
    QFrame#Panel, QFrame#Banner {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; }}
    QLabel {{ background: transparent; }}
    QLabel#Dim {{ color: {TEXT_DIM}; }}
    QLabel#SectionTitle {{ color: {TEXT_DIM}; font-weight: bold; text-transform: uppercase; }}
    QLabel#Badge {{ font-size: {m.badge_pt}pt; font-weight: bold; padding: 6px 10px; border-radius: 6px;
                    color: {BG}; }}
    QLabel#Remedy {{ color: {AMBER}; }}
    QLabel#Error {{ color: {RED}; }}
    QPushButton {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 6px;
                   min-height: {m.target}px; min-width: {m.target}px; padding: 0 14px; }}
    QPushButton:pressed {{ background: {BORDER}; }}
    QPushButton:disabled {{ color: {TEXT_DIM}; border-color: {PANEL_2}; }}
    QPushButton#Primary {{ background: {AMBER}; color: {BG}; font-weight: bold; border: none; }}
    QPushButton#Primary:disabled {{ background: {PANEL_2}; color: {TEXT_DIM}; }}
    QCheckBox {{ min-height: {m.target}px; spacing: 10px; }}
    QCheckBox::indicator {{ width: {max(22, m.target // 2)}px; height: {max(22, m.target // 2)}px; }}
    QListWidget {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 6px; }}
    QListWidget::item {{ min-height: {m.target}px; padding: 4px 8px; }}
    QListWidget::item:selected {{ background: {AMBER}; color: {BG}; }}
    QTableView {{ background: {PANEL}; alternate-background-color: {PANEL_2}; gridline-color: {BORDER};
                  selection-background-color: #3a4652; selection-color: {TEXT}; border: 1px solid {BORDER}; }}
    QHeaderView::section {{ background: {PANEL_2}; color: {TEXT}; border: none; border-right: 1px solid {BORDER};
                            padding: 4px 8px; min-height: {m.target}px; font-weight: bold; }}
    QScrollBar:vertical {{ width: {max(14, m.target // 3)}px; background: {PANEL}; }}
    QScrollBar:horizontal {{ height: {max(14, m.target // 3)}px; background: {PANEL}; }}
    QScrollBar::handle {{ background: {BORDER}; border-radius: 4px; min-height: 40px; min-width: 40px; }}
    QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; }}
    QStatusBar QLabel {{ padding: 0 10px; }}
    QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid {BORDER}; }}
    QDialog {{ background: {BG}; }}
    """
