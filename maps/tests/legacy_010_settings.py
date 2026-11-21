# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""User settings (``~/.config/task-maps/settings.json``, schema 1). Unknown or corrupt files fall
back to defaults without being overwritten until the user changes something."""

import json
from dataclasses import asdict, dataclass, field

from task_maps import atomic, paths

SCHEMA = 1


@dataclass
class Settings:
    data_dir: str = ""                    # empty = $XDG_DATA_HOME/task-maps
    coord_format: str = "decimal"         # decimal | dms
    cache_tiles: int = 512                # in-memory decoded tile cache (bounded LRU)
    layer: str = ""                       # last map file (path)
    view: list = field(default_factory=lambda: [39.5, -98.35, 4.0])   # lat, lon, zoom
    follow: bool = False
    ua_contact: str = ""                  # optional contact appended to the User-Agent
    gpsd_port: int = 2947
    load_error: str = ""

    def resolved_data_dir(self):
        from pathlib import Path
        return Path(self.data_dir) if self.data_dir.startswith("/") else paths.default_data_dir()


def load(path=None) -> Settings:
    path = path or (paths.config_dir() / "settings.json")
    s = Settings()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return s
    except (OSError, ValueError) as exc:
        s.load_error = f"{path}: {exc} (defaults used)"
        return s
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        s.load_error = f"{path}: unknown schema (defaults used)"
        return s
    if isinstance(doc.get("data_dir"), str):
        s.data_dir = doc["data_dir"]
    if doc.get("coord_format") in ("decimal", "dms"):
        s.coord_format = doc["coord_format"]
    if isinstance(doc.get("cache_tiles"), int) and 64 <= doc["cache_tiles"] <= 8192:
        s.cache_tiles = doc["cache_tiles"]
    if isinstance(doc.get("layer"), str):
        s.layer = doc["layer"]
    v = doc.get("view")
    if isinstance(v, list) and len(v) == 3 and all(isinstance(x, (int, float)) for x in v):
        s.view = [max(-85.0, min(85.0, v[0])), max(-180.0, min(180.0, v[1])), max(0.0, min(20.0, v[2]))]
    if isinstance(doc.get("follow"), bool):
        s.follow = doc["follow"]
    if isinstance(doc.get("ua_contact"), str):
        s.ua_contact = doc["ua_contact"][:120]
    if isinstance(doc.get("gpsd_port"), int) and 1 <= doc["gpsd_port"] <= 65535:
        s.gpsd_port = doc["gpsd_port"]
    return s


def save(s: Settings, path=None):
    path = path or (paths.config_dir() / "settings.json")
    d = asdict(s)
    d.pop("load_error", None)
    d["schema"] = SCHEMA
    atomic.write_text(path, json.dumps(d, indent=2, sort_keys=True) + "\n")
