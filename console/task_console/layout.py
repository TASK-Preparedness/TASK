# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Layout metrics (PHASE-2.md sections 7.2, 7.7, 7.8, 7.9).

All sizes are logical pixels at scale 1.0 and are multiplied by the UI scale.
"""

from dataclasses import dataclass

COMPACT_WIDTH = 1280
COMPACT_HEIGHT = 720


def is_compact(width: int, height: int) -> bool:
    return width < COMPACT_WIDTH or height < COMPACT_HEIGHT


@dataclass(frozen=True)
class Metrics:
    scale: float = 1.0
    compact: bool = False

    def px(self, value: float) -> int:
        return int(round(value * self.scale))

    @property
    def font_px(self) -> int:
        return self.px(16)

    @property
    def small_font_px(self) -> int:
        return self.px(16)

    @property
    def title_font_px(self) -> int:
        return self.px(24)

    @property
    def target(self) -> int:
        return self.px(48)

    @property
    def spacing(self) -> int:
        return self.px(8)

    @property
    def strip_height(self) -> int:
        return self.px(56)

    @property
    def rail_width(self) -> int:
        return self.px(72 if self.compact else 104)

    @property
    def rail_item_height(self) -> int:
        return self.px(72)

    @property
    def tile_width(self) -> int:
        return self.px(320)

    @property
    def tile_height(self) -> int:
        return self.px(168)

    @property
    def max_columns(self) -> int:
        return 2 if self.compact else 4

    @property
    def row_height(self) -> int:
        return self.px(48)

    @property
    def focus_width(self) -> int:
        return 3

    @property
    def dialog_max(self):
        return (1000, 560) if self.compact else (self.px(1100), self.px(800))
