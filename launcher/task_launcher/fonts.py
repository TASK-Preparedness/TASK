# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Font selection: Inter (SIL OFL-1.1) from the Debian package ``fonts-inter`` when installed.

Inter is NOT bundled in the package (02-launcher-ui.md section 6: OFL fonts stay a separate Debian
package). ``fonts-inter`` is a Recommends of task-launcher. Fallback order: Noto Sans, DejaVu Sans,
then the Qt default. The chosen family is reported in Settings -> About.
"""

PREFERRED = ("Inter", "Inter Variable", "Noto Sans", "DejaVu Sans")
_chosen = None


def choose_family() -> str:
    global _chosen
    if _chosen is not None:
        return _chosen
    from PySide6.QtGui import QFontDatabase

    families = set(QFontDatabase.families())
    for name in PREFERRED:
        if name in families:
            _chosen = name
            return name
    from PySide6.QtGui import QGuiApplication

    _chosen = QGuiApplication.font().family()
    return _chosen


def font(px: float, weight=None, family: str = None):
    from PySide6.QtGui import QFont

    f = QFont(family or choose_family())
    f.setPixelSize(max(1, round(px)))
    if weight is not None:
        f.setWeight(weight)
    return f


def reset_cache() -> None:
    global _chosen
    _chosen = None
