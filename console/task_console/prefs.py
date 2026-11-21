# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Console preferences and window state (PHASE-2.md section 11).

console.toml holds the scale, the idle-lock minutes (1-10), the last panel and the kinetic-scroll
switch only.
state.toml holds window geometry only; fullscreen is never stored. No tokens,
usernames, passwords or device data are ever written.
"""

import logging
import os
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib

logger = logging.getLogger("task_console")

SCALES = (1.0, 1.25, 1.5)
DEFAULT_SCALE = 1.0  # D8
DEFAULT_IDLE_MINUTES = 10
MAX_IDLE_MINUTES = 10
MIN_IDLE_MINUTES = 1
PANELS = ("home", "core", "devices")


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "task-console"


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "task-console"


def clamp_idle(value) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return DEFAULT_IDLE_MINUTES
    return max(MIN_IDLE_MINUTES, min(MAX_IDLE_MINUTES, minutes))


def _read(path: Path) -> dict:
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError):
        logger.warning("ignoring unreadable %s", path.name)
        return {}


def _write(path: Path, lines: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name("." + path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


class Prefs:
    def __init__(self, directory: Path = None) -> None:
        self.path = (directory or config_dir()) / "console.toml"
        data = _read(self.path)
        scale = data.get("scale", DEFAULT_SCALE)
        self.scale = float(scale) if isinstance(scale, (int, float)) and float(scale) in SCALES else DEFAULT_SCALE
        self.idle_lock_minutes = clamp_idle(data.get("idle_lock_minutes", DEFAULT_IDLE_MINUTES))
        self.kinetic_scroll = data.get("kinetic_scroll") is True
        panel = data.get("last_panel", "home")
        self.last_panel = panel if panel in PANELS else "home"

    def save(self) -> None:
        try:
            _write(self.path, [
                f"scale = {self.scale}",
                f"idle_lock_minutes = {clamp_idle(self.idle_lock_minutes)}",
                f'last_panel = "{self.last_panel if self.last_panel in PANELS else "home"}"',
                f"kinetic_scroll = {'true' if self.kinetic_scroll else 'false'}",
            ])
        except OSError as exc:
            logger.warning("could not save preferences (%s)", type(exc).__name__)


class WindowState:
    def __init__(self, directory: Path = None) -> None:
        self.path = (directory or state_dir()) / "state.toml"
        data = _read(self.path)
        geometry = data.get("geometry")
        self.geometry = None
        if isinstance(geometry, list) and len(geometry) == 4 and all(isinstance(v, int) for v in geometry):
            self.geometry = geometry

    def save(self, x, y, width, height) -> None:
        try:
            _write(self.path, [f"geometry = [{int(x)}, {int(y)}, {int(width)}, {int(height)}]"])
        except OSError as exc:
            logger.warning("could not save window state (%s)", type(exc).__name__)
