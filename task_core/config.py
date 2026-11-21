# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import os
from dataclasses import dataclass
from pathlib import Path

from task_core.errors import ConfigError


def read_toml(text: str) -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib
    document = tomllib.loads(text)
    if not isinstance(document, dict):
        raise ConfigError("config must be a table")
    return document


def validate_socket(value) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise ConfigError("socket must be an absolute filesystem path")
    if (
        not value.startswith("/")
        or value.endswith("/")
        or "\x00" in value
        or "://" in value
    ):
        raise ConfigError("socket must be an absolute filesystem path")
    return value


@dataclass
class Config:
    socket: str
    state_dir: Path
    share_dir: Path
    auth_file: Path
    # Optional (Phase 2). None means the fixed default /etc/task/sessions.toml.
    sessions_file: Path | None = None


def load_config(path: Path) -> Config:
    if not path.is_file():
        raise ConfigError("config file missing")
    try:
        document = read_toml(path.read_text(encoding="utf-8"))
    except ConfigError:
        raise
    except Exception:
        raise ConfigError("config file rejected") from None
    socket = validate_socket(document.get("socket"))
    state_dir = _dir_value(document.get("state_dir"), "state_dir")
    share_dir = _dir_value(document.get("share_dir"), "share_dir")
    auth_file = _dir_value(document.get("auth_file"), "auth_file")
    sessions_file = None
    if "sessions_file" in document:
        sessions_file = _dir_value(document.get("sessions_file"), "sessions_file")
    if os.environ.get("RAIN_STATE_DIR"):
        state_dir = Path(os.environ["RAIN_STATE_DIR"])
    if os.environ.get("RAIN_SHARE_DIR"):
        share_dir = Path(os.environ["RAIN_SHARE_DIR"])
    return Config(
        socket=socket,
        state_dir=state_dir,
        share_dir=share_dir,
        auth_file=auth_file,
        sessions_file=sessions_file,
    )


def _dir_value(value, label: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise ConfigError(f"{label} must be an absolute path")
    return Path(value)
