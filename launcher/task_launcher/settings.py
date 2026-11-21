# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Per-user launcher settings: ~/.config/task-launcher/settings.json (0600, atomic writes).

No secrets and no privileged settings live here. Invalid values fall back to defaults field by
field, so a damaged file never prevents the launcher from starting.
"""

from dataclasses import asdict, dataclass

from task_launcher import atomic, paths
from task_launcher.layout import MODES

SCALES = (1.0, 1.25, 1.5)
START_MODES = ("maximized", "windowed", "fullscreen")
BRANDINGS = ("default", "rain", "task", "custom")
MOTION = ("system", "on", "off")
FILE_NAME = "settings.json"
SCHEMA = 1


@dataclass
class Settings:
    branding: str = "default"           # default = system default (/etc) or T.A.S.K.; 'rain' = legacy alias of 'task'
    custom_title: str = ""
    custom_subtitle: str = ""
    layout: str = "auto"                 # auto (Large, approved default) | large | standard | compact
    scale: float = 1.0
    start_mode: str = "maximized"
    show_planned: bool = True
    idle_lock_minutes: int = 10          # 1..10 (Phase 2 D11 rule: never above 10)
    reduce_motion: str = "system"        # system | on | off (motion.py)

    def normalized(self) -> "Settings":
        s = Settings()
        s.branding = self.branding if self.branding in BRANDINGS else "default"
        s.custom_title = self.custom_title[:24] if isinstance(self.custom_title, str) else ""
        s.custom_subtitle = self.custom_subtitle[:60] if isinstance(self.custom_subtitle, str) else ""
        s.layout = self.layout if self.layout in MODES else "auto"
        try:
            s.scale = min(SCALES, key=lambda v: abs(v - float(self.scale)))
        except (TypeError, ValueError):
            s.scale = 1.0
        s.start_mode = self.start_mode if self.start_mode in START_MODES else "maximized"
        s.show_planned = self.show_planned if isinstance(self.show_planned, bool) else True
        try:
            s.idle_lock_minutes = max(1, min(10, int(self.idle_lock_minutes)))
        except (TypeError, ValueError):
            s.idle_lock_minutes = 10
        s.reduce_motion = self.reduce_motion if self.reduce_motion in MOTION else "system"
        return s


def settings_path():
    return paths.config_dir() / FILE_NAME


def load(path=None) -> Settings:
    doc = atomic.read_json(path or settings_path())
    s = Settings()
    if isinstance(doc, dict):
        for key in asdict(s):
            if key in doc:
                setattr(s, key, doc[key])
    return s.normalized()


def save(settings: Settings, path=None) -> None:
    doc = asdict(settings.normalized())
    doc["schema"] = SCHEMA
    atomic.write_json(path or settings_path(), doc)
