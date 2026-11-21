# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""User configuration (config.toml, read-only) and app-written state (state.json).

Invalid or missing values never stop the app: defaults are used and a warning is recorded.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RadioConfig:
    autoconnect: bool = True
    handshake_deadline_s: int = 45
    link_probe_s: int = 120  # 0 disables the write-only heartbeat link probe
    reboot_grace_s: int = 60
    library_timeout_s: int = 300


@dataclass(frozen=True)
class RetentionConfig:
    node_observations_days: int = 30
    connection_events_days: int = 180
    radio_events_days: int = 30
    radio_events_max_rows: int = 200000
    nodes_unheard_days: int = 0  # 0 = keep forever


@dataclass(frozen=True)
class UiConfig:
    density: str = "auto"  # auto | touch | compact
    fullscreen: bool = False


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"


@dataclass(frozen=True)
class Config:
    radio: RadioConfig = field(default_factory=RadioConfig)
    retention: RetentionConfig = field(default_factory=RetentionConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


_CHOICES = {
    ("ui", "density"): {"auto", "touch", "compact"},
    ("logging", "level"): {"DEBUG", "INFO", "WARNING", "ERROR"},
}
_MIN = {
    ("radio", "handshake_deadline_s"): 35,
    ("radio", "link_probe_s"): 0,
    ("radio", "reboot_grace_s"): 10,
    ("radio", "library_timeout_s"): 30,
}


def _coerce_section(name: str, cls: type, raw: Any, warnings: list[str]) -> Any:
    default = cls()
    if raw is None:
        return default
    if not isinstance(raw, dict):
        warnings.append(f"[{name}] must be a table; using defaults")
        return default
    values = {}
    known = {f.name: f for f in fields(cls)}
    for key, val in raw.items():
        if key not in known:
            warnings.append(f"[{name}] unknown key '{key}' ignored")
            continue
        expected = type(getattr(default, key))
        ok = isinstance(val, expected) and not (expected is int and isinstance(val, bool))
        if not ok:
            warnings.append(f"[{name}] {key} must be {expected.__name__}; using default")
            continue
        if expected is str and key == "level":
            val = val.upper()
        choices = _CHOICES.get((name, key))
        if choices and val not in choices:
            warnings.append(f"[{name}] {key} must be one of {sorted(choices)}; using default")
            continue
        if expected is int:
            minimum = _MIN.get((name, key), 0)
            if val < minimum:
                warnings.append(f"[{name}] {key} must be >= {minimum}; using default")
                continue
        values[key] = val
    return replace(default, **values)


def parse_config(text: str) -> tuple[Config, list[str]]:
    warnings: list[str] = []
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return Config(), [f"config.toml is not valid TOML ({exc}); using defaults"]
    cfg = Config(
        radio=_coerce_section("radio", RadioConfig, data.get("radio"), warnings),
        retention=_coerce_section("retention", RetentionConfig, data.get("retention"), warnings),
        ui=_coerce_section("ui", UiConfig, data.get("ui"), warnings),
        logging=_coerce_section("logging", LoggingConfig, data.get("logging"), warnings),
    )
    for key in data:
        if key not in ("radio", "retention", "ui", "logging"):
            warnings.append(f"unknown section [{key}] ignored")
    return cfg, warnings


def load_config(path: Path) -> tuple[Config, list[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Config(), []
    except OSError as exc:
        return Config(), [f"cannot read {path}: {exc}; using defaults"]
    return parse_config(text)


DEFAULT_CONFIG_TEXT = """\
# T.A.S.K. Mesh Operations configuration. All keys are optional.
[radio]
autoconnect = true
handshake_deadline_s = 45
link_probe_s = 120        # 0 disables the heartbeat write probe
reboot_grace_s = 60

[retention]
node_observations_days = 30
connection_events_days = 180
radio_events_days = 30
radio_events_max_rows = 200000
nodes_unheard_days = 0    # 0 = keep forever

[ui]
density = "auto"          # auto | touch | compact
fullscreen = false

[logging]
level = "INFO"            # DEBUG | INFO | WARNING | ERROR (meshtastic library is always capped at WARNING)
"""


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class StateStore:
    """Thread-safe JSON state (pinned device, last successful port). Corrupt file -> empty state."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self.load_warning: Optional[str] = None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = raw
            else:
                self.load_warning = "state.json is not an object; starting fresh"
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            self.load_warning = f"state.json unreadable ({exc}); starting fresh"

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if value is None:
                self._data.pop(key, None)
            else:
                self._data[key] = value
            text = json.dumps(self._data, indent=2, sort_keys=True)
        try:
            atomic_write_text(self._path, text)
        except OSError:
            log.warning("could not write state file", extra={"event": "state.write_error"})
