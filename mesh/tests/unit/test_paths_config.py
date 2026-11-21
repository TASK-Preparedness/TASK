# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import json
import stat
from pathlib import Path

from task_mesh.core.config import (
    DEFAULT_CONFIG_TEXT,
    Config,
    StateStore,
    load_config,
    parse_config,
)
from task_mesh.core.paths import resolve_paths


def test_xdg_env_overrides(tmp_path):
    env = {"XDG_CONFIG_HOME": str(tmp_path / "c"), "XDG_STATE_HOME": str(tmp_path / "s"),
           "XDG_DATA_HOME": str(tmp_path / "d"), "XDG_CACHE_HOME": str(tmp_path / "k"), "HOME": "/nonexistent"}
    p = resolve_paths(env)
    assert p.config_file == tmp_path / "c" / "task-mesh" / "config.toml"
    assert p.state_file == tmp_path / "s" / "task-mesh" / "state.json"
    assert p.log_file == tmp_path / "s" / "task-mesh" / "log" / "task-mesh.jsonl"
    assert p.db_file == tmp_path / "d" / "task-mesh" / "task-mesh.sqlite3"
    assert p.cache_dir == tmp_path / "k" / "task-mesh"


def test_xdg_defaults_follow_home_and_ignore_relative(tmp_path):
    home = tmp_path / "someone"
    p = resolve_paths({"HOME": str(home), "XDG_DATA_HOME": "relative/path"})
    assert p.config_dir == home / ".config" / "task-mesh"
    assert p.state_dir == home / ".local" / "state" / "task-mesh"
    assert p.data_dir == home / ".local" / "share" / "task-mesh"  # relative XDG value ignored per spec
    assert p.cache_dir == home / ".cache" / "task-mesh"


def test_no_hardcoded_user_paths_in_source():
    root = Path(__file__).resolve().parents[2] / "task_mesh"
    for f in root.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert "/home/pi" not in text and "/home/joshua" not in text.lower(), f
        assert "chmod 777" not in text and "0o777" not in text, f


def test_ensure_creates_private_dirs(tmp_path):
    p = resolve_paths({"HOME": str(tmp_path)})
    p.ensure()
    for d in (p.config_dir, p.state_dir, p.log_dir, p.data_dir, p.cache_dir):
        assert d.is_dir()
        assert stat.S_IMODE(d.stat().st_mode) & 0o077 == 0


def test_default_config_text_parses_to_defaults():
    cfg, warnings = parse_config(DEFAULT_CONFIG_TEXT)
    assert warnings == []
    assert cfg == Config()


def test_config_missing_file_is_defaults(tmp_path):
    cfg, warnings = load_config(tmp_path / "nope.toml")
    assert cfg == Config() and warnings == []


def test_config_invalid_toml_falls_back_with_warning():
    cfg, warnings = parse_config("this is = = not toml")
    assert cfg == Config()
    assert warnings and "not valid TOML" in warnings[0]


def test_config_bad_types_and_values_warn():
    cfg, warnings = parse_config(
        '[radio]\nautoconnect = "yes"\nhandshake_deadline_s = 5\n[ui]\ndensity = "huge"\n[bogus]\nx=1\n')
    assert cfg.radio.autoconnect is True
    assert cfg.radio.handshake_deadline_s >= 35
    assert cfg.ui.density == "auto"
    assert len(warnings) >= 3


def test_config_valid_overrides():
    cfg, warnings = parse_config('[radio]\nautoconnect = false\nlink_probe_s = 0\n[retention]\n'
                                 'node_observations_days = 7\n[ui]\ndensity = "touch"\n')
    assert warnings == []
    assert cfg.radio.autoconnect is False and cfg.radio.link_probe_s == 0
    assert cfg.retention.node_observations_days == 7
    assert cfg.ui.density == "touch"


def test_state_store_roundtrip_and_delete(tmp_path):
    s = StateStore(tmp_path / "st" / "state.json")
    s.set("pinned_port", {"by_id": "/dev/serial/by-id/x", "vid": 4292})
    s2 = StateStore(tmp_path / "st" / "state.json")
    assert s2.get("pinned_port")["vid"] == 4292
    s2.set("pinned_port", None)
    assert StateStore(tmp_path / "st" / "state.json").get("pinned_port") is None
    assert json.loads((tmp_path / "st" / "state.json").read_text()) == {}


def test_state_store_corrupt_file(tmp_path):
    f = tmp_path / "state.json"
    f.write_text("{not json")
    s = StateStore(f)
    assert s.get("x") is None and s.load_warning
