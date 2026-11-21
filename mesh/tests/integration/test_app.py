# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""App entry: root refusal (AT-02), --version, forget-user-data, corrupt DB banner (AT-16), DB error UI."""

import io
import os

import pytest

from task_mesh import app as appmod
from task_mesh.app import ROOT_MESSAGE, build_application, forget_user_data, main
from task_mesh.core.paths import resolve_paths


def test_refuses_root(capsys, monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert main([], geteuid=lambda: 0) == 2
    err = capsys.readouterr().err
    assert "must not be run as root" in err and "dialout" in err
    assert "root" in ROOT_MESSAGE


def test_refuses_root_headless_never_blocks_on_dialog(capsys, monkeypatch):
    # Regression: with DISPLAY set but QT_QPA_PLATFORM=offscreen a modal dialog
    # nobody can see would block forever.
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    import PySide6.QtWidgets as qtw

    def boom(*a, **k):
        raise AssertionError("dialog must not be shown headless")

    monkeypatch.setattr(qtw.QMessageBox, "critical", boom)
    assert main([], geteuid=lambda: 0) == 2
    assert "must not be run as root" in capsys.readouterr().err


def test_version(capsys):
    assert main(["--version"], geteuid=lambda: 1000) == 0
    assert capsys.readouterr().out.strip() == "task-mesh 0.3.1"


def test_forget_user_data_requires_yes(tmp_path):
    p = resolve_paths({"HOME": str(tmp_path)})
    p.ensure()
    (p.data_dir / "x").write_text("keep")
    out = io.StringIO()
    assert forget_user_data(p, ask=lambda _: "no", out=out) == 1 and (p.data_dir / "x").exists()
    assert forget_user_data(p, ask=lambda _: "yes", out=out) == 0
    assert not p.data_dir.exists() and not p.config_dir.exists()


def _ctx(xdg, **kw):
    return build_application(env=xdg, discover=lambda: [], hotplug=None, console_log=False, **kw)


def test_at16_corrupt_db_quarantined_banner_and_usable(qtbot, xdg):
    p = resolve_paths(xdg)
    p.ensure()
    p.db_file.write_bytes(os.urandom(4096))
    ctx = _ctx(xdg)
    try:
        qtbot.waitUntil(lambda: ctx.radio.last_snapshot.state == "NO_DEVICE", timeout=3000)
        assert ctx.window.banner.isVisibleTo(ctx.window)
        assert "moved aside" in ctx.window.banner.label.text()
        assert list(p.data_dir.glob("task-mesh.sqlite3.corrupt-*"))
        qtbot.waitUntil(lambda: ctx.window.status.db_label.text() == "DB: OK", timeout=3000)
    finally:
        ctx.shutdown()


def test_newer_schema_shows_db_error_not_crash(qtbot, xdg):
    import sqlite3

    p = resolve_paths(xdg)
    p.ensure()
    c = sqlite3.connect(p.db_file)
    c.execute("PRAGMA user_version = 77")
    c.close()
    ctx = _ctx(xdg)
    try:
        assert "Database unavailable" in ctx.window.banner.label.text()
        qtbot.waitUntil(lambda: ctx.window.status.db_label.text() == "DB: ERROR", timeout=3000)
        qtbot.waitUntil(lambda: ctx.radio.last_snapshot.state == "NO_DEVICE", timeout=3000)
    finally:
        ctx.shutdown()


def test_config_warning_shown_in_banner(qtbot, xdg):
    p = resolve_paths(xdg)
    p.ensure()
    p.config_file.write_text("[radio\nbroken")
    ctx = _ctx(xdg, no_autoconnect=True)
    try:
        assert "not valid TOML" in ctx.window.banner.label.text()
        qtbot.waitUntil(lambda: ctx.radio.last_snapshot.state == "IDLE", timeout=2000)
    finally:
        ctx.shutdown()


def test_startup_logs_versions_and_platform(qtbot, xdg):
    ctx = _ctx(xdg, no_autoconnect=True)
    ctx.shutdown()
    for h in __import__("logging").getLogger().handlers:
        h.flush()
    text = ctx.paths.log_file.read_text()
    assert '"event": "app.start"' in text and "qt.platform=offscreen" in text and '"versions"' in text


def test_excepthook_shows_banner_not_crash(qtbot, xdg, monkeypatch):
    import sys

    ctx = _ctx(xdg, no_autoconnect=True)
    try:
        holder = {"ctx": ctx}
        monkeypatch.setattr(sys, "excepthook", sys.excepthook)
        appmod._install_excepthook(holder)
        try:
            raise ValueError("boom")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        assert "Internal error: ValueError" in ctx.window.banner.label.text()
    finally:
        ctx.shutdown()


def test_vendor_path_helper(monkeypatch, tmp_path):
    vend = tmp_path / "_vendor"
    (vend / "meshtastic").mkdir(parents=True)
    monkeypatch.setattr(appmod, "VENDOR_DIR", vend)
    import sys

    monkeypatch.setattr(sys, "path", list(sys.path))
    appmod._ensure_vendor_path()
    assert sys.path[0] == str(vend)
