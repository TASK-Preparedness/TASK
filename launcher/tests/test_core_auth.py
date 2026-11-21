# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Core link and sign-in against the real task-core server (tests/p2fixtures.py, TEST DATA:
accounts dragon/op, golden devices). The launcher must also work while Core is down."""

import importlib.util
import json
import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

import task_core
from p2fixtures import DRAGON_PW, OP_PW
from task_launcher.core.link import BACKOFF, STEADY_RETRY, backoff_delay

REPO = Path(__file__).resolve().parents[2]


def connected(qtbot, w, timeout=5000):
    qtbot.waitUntil(lambda: w.link.live and w.link.health is not None, timeout=timeout)


def sign_in(qtbot, w, user, password):
    dlg = w.request_sign_in()
    dlg.username.setText(user)
    dlg.password.setText(password)
    dlg.submit.click()
    assert dlg.password.text() == ""            # cleared before the request completes
    return dlg


def test_footer_shows_real_core_version(qtbot, launcher, p2env):
    core = p2env()
    w = launcher(core.config.socket)
    connected(qtbot, w)
    assert w.home.core_label.text() == f"T.A.S.K. Core · connected · {task_core.__version__}"
    assert "0.2.0" not in w.home.core_label.text() or task_core.__version__ == "0.2.0"
    assert w.home.auth_chip.text() == "Public · Sign in"
    assert w.link.counts == {"total": 3, "connected": 3, "disconnected": 0}


def test_works_while_core_is_down_then_connects(qtbot, launcher, p2env):
    core = p2env(do_open=False)
    w = launcher(core.config.socket)
    qtbot.waitUntil(lambda: w.link.link == "offline", timeout=3000)
    assert w.home.core_label.text().startswith("T.A.S.K. Core · disconnected — retry in")
    assert len(w.home.tiles) == 12                         # the launcher is fully usable
    sysw = w.open_builtin("system")
    assert sysw.isVisible()
    core.open()
    connected(qtbot, w, timeout=8000)
    assert w.link.retry_delays[0] == pytest.approx(BACKOFF[0])


def test_core_stop_goes_offline_and_reconnects(qtbot, launcher, p2env):
    core = p2env()
    w = launcher(core.config.socket)
    connected(qtbot, w)
    base = core._base
    core.close()
    qtbot.waitUntil(lambda: not w.link.live, timeout=5000)
    assert "disconnected" in w.home.core_label.text() or "connecting" in w.home.core_label.text()
    core2 = p2env(base=base, state_dir=base / "state")
    connected(qtbot, w, timeout=10000)
    assert w.link.version() == task_core.__version__
    core2.close()


def test_backoff_schedule():
    assert [round(backoff_delay(i, rng=lambda: 0.5), 3) for i in range(7)] == list(BACKOFF) + [STEADY_RETRY] * 2
    assert backoff_delay(0, rng=lambda: 1.0) == pytest.approx(BACKOFF[0] * 1.2)
    assert backoff_delay(0, rng=lambda: 0.0) == pytest.approx(BACKOFF[0] * 0.8)


def test_operator_sign_in_and_role_aware_devices(qtbot, launcher, p2env):
    core = p2env()
    w = launcher(core.config.socket)
    connected(qtbot, w)
    dev = w.open_builtin("devices")              # task-console is not installed on this box
    assert "task-console is not installed" in dev.banner.text()
    assert dev.sign_in.isVisible() and not dev.table.isVisible()
    assert "3 connected" in dev.counts.text()
    sign_in(qtbot, w, "op", OP_PW)
    qtbot.waitUntil(lambda: w.link.role == "operator", timeout=5000)
    assert w.home.auth_chip.text() == "op · operator"
    qtbot.waitUntil(lambda: dev.table.rowCount() == 3, timeout=5000)
    products = {dev.table.item(r, 0).text() for r in range(3)}
    assert "u-blox 7 - GPS/GNSS Receiver" in products
    w.link.logout()
    assert w.home.auth_chip.text() == "Public · Sign in"
    assert not dev.table.isVisible() and w.link.devices is None


def test_wrong_password_and_forbidden_client(qtbot, launcher, p2env):
    core = p2env()
    w = launcher(core.config.socket)
    connected(qtbot, w)
    dlg = sign_in(qtbot, w, "op", "wrong password")
    qtbot.waitUntil(lambda: "Wrong username or password" in dlg.message.text(), timeout=5000)
    assert w.link.role == "public"
    dlg.reject()
    core2 = p2env(clients=[])                  # this uid not in sessions.toml [clients]
    w2 = launcher(core2.config.socket)
    connected(qtbot, w2)
    dlg2 = sign_in(qtbot, w2, "dragon", DRAGON_PW)
    qtbot.waitUntil(lambda: "sessions.toml [clients]" in dlg2.message.text(), timeout=5000)


def test_password_never_stored_or_logged(qtbot, launcher, p2env, isolated_home, caplog):
    core = p2env()
    w = launcher(core.config.socket)
    connected(qtbot, w)
    caplog.set_level("DEBUG")
    sign_in(qtbot, w, "dragon", DRAGON_PW)
    qtbot.waitUntil(lambda: w.link.role == "administrator", timeout=5000)
    assert DRAGON_PW not in caplog.text
    for p in isolated_home.rglob("*"):
        if p.is_file():
            data = p.read_bytes()
            assert DRAGON_PW.encode() not in data, p
            assert w.link.client._token is None or w.link.client._token.encode() not in data, p
    w.link.lock("user")
    assert w.overlay.isVisible() and w.link.role == "public"
    w.overlay.public.click()
    assert not w.overlay.isVisible()


def test_idle_lock(qtbot, launcher, p2env):
    now = [1000.0]
    core = p2env()
    w = launcher(core.config.socket, idle_clock=lambda: now[0])
    connected(qtbot, w)
    sign_in(qtbot, w, "op", OP_PW)
    qtbot.waitUntil(lambda: w.link.signed_in, timeout=5000)
    w.note_input()
    now[0] += w.settings.idle_lock_minutes * 60 + 1
    w._on_tick()
    assert w.link.locked and w.overlay.isVisible() and not w.link.signed_in


def test_too_old_core(qtbot, launcher, tmp_path):
    spec = importlib.util.spec_from_file_location("console_helpers", REPO / "console" / "tests" / "helpers.py")
    import sys
    sys.path.insert(0, str(REPO / "console"))
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    sock = tmp_path / "old.sock"
    old = helpers.fake_011_core(sock)
    w = launcher(str(sock))
    qtbot.waitUntil(lambda: w.link.link == "too-old", timeout=5000)
    assert "too old" in w.home.core_label.text()
    old.server.close()


def test_no_access_socket(qtbot, launcher, tmp_path):
    import socket as s
    path = tmp_path / "locked.sock"
    srv = s.socket(s.AF_UNIX, s.SOCK_STREAM)
    srv.bind(str(path))
    srv.listen(1)
    os.chmod(path, 0)
    try:
        w = launcher(str(path))
        if os.geteuid() != 0:
            qtbot.waitUntil(lambda: w.link.link == "no-access", timeout=5000)
            assert "no access" in w.home.core_label.text()
    finally:
        srv.close()


def test_sign_in_gate_for_role_restricted_tile(qtbot, launcher, p2env, tmp_path, safe_dir):
    from conftest import make_exec
    from task_launcher.registry.discovery import BUNDLED_APPS_DIR
    from task_launcher.registry.registry import Registry
    from task_launcher.registry.tilestore import TileStore

    exe = make_exec(safe_dir / "bin", "opapp", "exit 0")
    m = tmp_path / "m"
    m.mkdir()
    (m / "x.toml").write_text(f'manifest_version = 1\nid = "test.opapp"\nname = "Op App"\nversion = "1.0.0"\n'
                              f'min_role = "operator"\n[launch]\nexec = ["{exe}"]\n')
    reg = Registry(manifest_dirs=[(BUNDLED_APPS_DIR, "package"), (m, "admin")], desktop_dirs=[],
                   store=TileStore(tmp_path / "t.json"))
    core = p2env()
    w = launcher(core.config.socket, registry=reg)
    connected(qtbot, w)
    tw = w.home.tile_widget("app:test.opapp")
    assert tw.state_line == "Sign in to use"
    dlg = w.activate(tw.tile)
    assert dlg is w.sign_in_dialog and w._pending_after_login == "app:test.opapp"
    dlg.username.setText("op")
    dlg.password.setText(OP_PW)
    dlg.submit.click()
    qtbot.waitUntil(lambda: w.link.signed_in, timeout=5000)
    qtbot.waitUntil(lambda: "app:test.opapp" in w.procs.procs or w.runtime.get("app:test.opapp"), timeout=3000)


def test_no_session_token_written_on_shutdown(qtbot, launcher, p2env, isolated_home):
    core = p2env()
    w = launcher(core.config.socket)
    connected(qtbot, w)
    sign_in(qtbot, w, "op", OP_PW)
    qtbot.waitUntil(lambda: w.link.signed_in, timeout=5000)
    token = w.link.client._token
    w.shutdown()
    assert w.link.client._token is None
    for p in isolated_home.rglob("*"):
        if p.is_file():
            assert token.encode() not in p.read_bytes()
