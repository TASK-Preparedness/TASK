# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Tests 68 (password field, D4) and 70 (no secrets in console files). TEST DATA only."""

import unicodedata

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from helpers import gone, payload_spy
from p2fixtures import DRAGON_PW

GENERATED = "x7 \"'$`\\Q-pL;9 wE,b#2~kT<z?u!R^mN0 a+cV:j&Fh|yS*i)D(g]o[e{s}r%t=W@qZ_K.lB>8/Yd4U1"[:64]


def secrets_sent(seen):
    return [p["params"]["secret"] for p in seen if p["method"] == "session.login"]


def submit(c, username, text):
    dialog = c.window.request_sign_in()
    dialog.username.setText(username)
    dialog.password.edit.setText(text)
    dialog.submit.click()
    return dialog


def test_68_paste_paths_insert_exact_text(p2env, console):
    core = p2env()
    c = console(core.config.socket)
    dialog = c.window.request_sign_in()
    field = dialog.password
    clipboard = QApplication.clipboard()
    exact = "  pass word \u00e9 \U0001f511  "
    for how in ("ctrl+v", "shift+insert", "button"):
        field.clear()
        clipboard.setText(exact)
        field.edit.setFocus()
        if how == "ctrl+v":
            QTest.keyClick(field.edit, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        elif how == "shift+insert":
            QTest.keyClick(field.edit, Qt.Key.Key_Insert, Qt.KeyboardModifier.ShiftModifier)
        else:
            field.paste_button.click()
        assert field.text() == exact, how
    assert field.paste_button.isVisible() and field.paste_button.text() == "Paste"
    # echo mode, copy/cut disabled, sensitive hints, no maxLength
    edit = field.edit
    assert edit.echoMode() == QLineEdit.EchoMode.Password
    assert edit.maxLength() == QLineEdit().maxLength()  # Qt's default: never set by the console
    hints = edit.inputMethodHints()
    for hint in (Qt.InputMethodHint.ImhSensitiveData, Qt.InputMethodHint.ImhNoPredictiveText,
                 Qt.InputMethodHint.ImhNoAutoUppercase):
        assert hints & hint
    clipboard.setText("untouched")
    edit.selectAll()
    edit.copy()
    QTest.keyClick(edit, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert clipboard.text() == "untouched" and edit.text() == exact
    edit.cut()  # Qt deletes the selection but never copies it out of a password field
    assert clipboard.text() == "untouched"
    dialog.reject()


@pytest.mark.parametrize("text", [
    "a" * 8, "b" * 64, "c" * 256, "\U0001f511" * 256,
    "\u5bc6\u7801\u5bc6\u7801\u5bc6\u7801\u5bc6\u7801",  # CJK
    "pa\u0073\u0301sword",  # combining mark (NFD form kept)
    unicodedata.normalize("NFD", "caf\u00e9 cr\u00e8me"),
    "  leading", "trailing  ", "in  ternal", " " * 8, GENERATED,
])
def test_68_sent_byte_exact_without_client_normalization(p2env, console, text):
    core = p2env()
    seen = payload_spy(core)
    c = console(core.config.socket)
    dialog = submit(c, "nobody", text)
    c.qtbot.waitUntil(lambda: bool(secrets_sent(seen)), timeout=3000)
    assert secrets_sent(seen) == [text]
    dialog.reject()


def test_68_257_characters_show_the_limit_and_send_nothing(p2env, console):
    core = p2env()
    seen = payload_spy(core)
    c = console(core.config.socket)
    for text in ("d" * 257, "\U0001f511" * 257):
        dialog = submit(c, "dragon", text)
        assert dialog.message.text() == "Passwords are at most 256 characters"
        dialog.reject()
    c.settle(200)
    assert secrets_sent(seen) == []


def test_68_rate_limited_message_verbatim_and_sign_in_disabled(p2env, console):
    core = p2env()
    c = console(core.config.socket)
    for _ in range(5):
        dialog = submit(c, "dragon", "wrong password!")
        c.qtbot.waitUntil(lambda: not dialog.busy, timeout=3000)
        dialog.reject()
    dialog = submit(c, "dragon", DRAGON_PW)
    c.qtbot.waitUntil(lambda: not dialog.busy, timeout=3000)
    assert dialog.message.text() == "too many attempts, retry in 30 s"
    assert not dialog.submit.isEnabled() and dialog._blocked.isActive()
    assert 29000 <= dialog._blocked.remainingTime() <= 30000
    assert c.controller.role == "public"


@pytest.fixture
def file_log():
    import logging

    from task_console import app

    log = logging.getLogger("task_console")
    saved = list(log.handlers)
    log.handlers = []
    app.setup_logging(to_file=True)
    yield
    for handler in log.handlers:
        handler.close()
    log.handlers = saved


def test_70_no_secrets_in_console_files(p2env, console, isolated_home, file_log):
    core = p2env()
    c = console(core.config.socket)
    c.sign_in("dragon")
    token = c.client._token
    c.window.set_scale(1.25)
    c.window.show_panel("devices")
    c.controller.lock("test")
    c.window.close()
    files = [p for p in isolated_home.rglob("*") if p.is_file()]
    names = {p.name for p in files}
    assert {"console.toml", "state.toml", "console.log"} <= names
    assert b"console locked" in (isolated_home / ".local" / "state" / "task-console" / "console.log").read_bytes()
    for path in files:
        data = path.read_bytes()
        assert token.encode() not in data, path
        assert DRAGON_PW.encode() not in data, path
        assert b"dev_" not in data and b"0001" not in data, path
        if path.name in ("console.toml", "state.toml"):
            assert b"dragon" not in data, path
        assert oct(path.stat().st_mode & 0o777) == "0o600", path
    assert (isolated_home / ".config" / "task-console" / "console.toml").read_text().startswith("scale = 1.25")
