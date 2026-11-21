# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""XDG Base Directory resolution. Qt-free; no hard-coded users or home paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

APP_DIR = "task-mesh"


def _xdg(env: Mapping[str, str], var: str, default_rel: str, home: Path) -> Path:
    value = env.get(var, "").strip()
    # The XDG spec says relative paths must be ignored.
    if value and os.path.isabs(value):
        return Path(value)
    return home / default_rel


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    state_dir: Path
    data_dir: Path
    cache_dir: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def state_file(self) -> Path:
        return self.state_dir / "state.json"

    @property
    def log_dir(self) -> Path:
        return self.state_dir / "log"

    @property
    def log_file(self) -> Path:
        return self.log_dir / "task-mesh.jsonl"

    @property
    def db_file(self) -> Path:
        return self.data_dir / "task-mesh.sqlite3"

    def ensure(self) -> None:
        """Create all directories (owner-only permissions)."""
        for d in (self.config_dir, self.state_dir, self.log_dir, self.data_dir, self.cache_dir):
            d.mkdir(parents=True, exist_ok=True, mode=0o700)

    def all_dirs(self) -> list[Path]:
        return [self.config_dir, self.state_dir, self.data_dir, self.cache_dir]


def resolve_paths(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> AppPaths:
    env = os.environ if env is None else env
    if home is None:
        home = Path(env["HOME"]) if env.get("HOME") else Path.home()
    return AppPaths(
        config_dir=_xdg(env, "XDG_CONFIG_HOME", ".config", home) / APP_DIR,
        state_dir=_xdg(env, "XDG_STATE_HOME", ".local/state", home) / APP_DIR,
        data_dir=_xdg(env, "XDG_DATA_HOME", ".local/share", home) / APP_DIR,
        cache_dir=_xdg(env, "XDG_CACHE_HOME", ".cache", home) / APP_DIR,
    )
