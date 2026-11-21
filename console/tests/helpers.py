# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Helpers for the console tests (TEST DATA only)."""

import copy
import json
import socket
import threading
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractButton, QApplication, QLabel, QLineEdit, QTableView, QTableWidget,
                               QWidget)

from p2fixtures import FakeClock, identifying_findings

REPO = Path(__file__).resolve().parents[2]


class Console:
    def __init__(self, qtbot, socket_path, size=(1920, 1080), idle_clock=None, **controller_kwargs):
        from task_console.app import build

        self.qtbot = qtbot
        self.idle_clock = idle_clock or FakeClock(0)
        self.window, self.controller, self.client = build(
            str(socket_path), idle_clock=self.idle_clock, controller_kwargs=controller_kwargs)
        qtbot.addWidget(self.window)
        self.window.resize(*size)
        self.window.show()
        self.window.resize(*size)
        self.window.activateWindow()
        qtbot.waitUntil(self.window.isActiveWindow, timeout=3000)
        self.controller.start()

    def wait_connected(self, timeout=5000):
        self.qtbot.waitUntil(lambda: self.controller.live and self.controller.modules is not None
                             and self.controller.counts is not None and self.controller.health is not None
                             and self.client.stream_active and self.controller.last_seq is not None,
                             timeout=timeout)
        self.settle()

    def activate(self):
        """Offscreen has no compositor to hand focus back to the window after a dialog closes."""
        self.window.activateWindow()
        self.qtbot.waitUntil(self.window.isActiveWindow, timeout=3000)

    def settle(self, ms=80):
        self.qtbot.wait(ms)

    def sign_in(self, username="dragon", password=None):
        from p2fixtures import DRAGON_PW, OP_PW

        password = password if password is not None else (DRAGON_PW if username == "dragon" else OP_PW)
        dialog = self.window.request_sign_in()
        dialog.username.setText(username)
        dialog.password.edit.setText(password)
        dialog.submit.click()
        self.qtbot.waitUntil(lambda: self.controller.signed_in or dialog.message.text() not in ("", "Signing in\u2026"),
                             timeout=5000)
        if self.controller.signed_in:
            self.qtbot.waitUntil(lambda: self.controller.devices is not None and self.client.stream_active,
                                 timeout=5000)
            self.settle()
            self.activate()
        return dialog

    def close(self):
        try:
            self.controller._retry.stop()
            self.client.close_stream()
            self.client.reset_rpc()
            self.window.close()
        except RuntimeError:
            pass


def gone(dialog) -> bool:
    """True once a dialog is closed (dialogs delete themselves on close)."""
    from shiboken6 import isValid

    return not isValid(dialog) or not dialog.isVisible()


def payload_spy(core):
    """Record every v2 request task-core receives, with the full payload (tests only)."""
    seen = []
    original = core.handle_v2

    def spy(payload, uid):
        seen.append(copy.deepcopy(payload))
        return original(payload, uid)

    core.handle_v2 = spy
    return seen


def widget_texts(root: QWidget, visible_only=True):
    """Text of the widget tree: labels, buttons, line edits, table models, tooltips, accessible names."""
    texts = []
    widgets = [root] + root.findChildren(QWidget)
    for widget in widgets:
        if visible_only and not widget.isVisible():
            continue
        for value in (widget.toolTip(), widget.accessibleName(), widget.accessibleDescription(),
                      widget.windowTitle() if widget.isWindow() else ""):
            if value:
                texts.append(value)
        if isinstance(widget, QLabel):
            texts.append(widget.text())
        elif isinstance(widget, QAbstractButton):
            texts.append(widget.text())
        elif isinstance(widget, QLineEdit) and widget.echoMode() == QLineEdit.EchoMode.Normal:
            texts.append(widget.text())
        if isinstance(widget, (QTableView, QTableWidget)):
            model = widget.model()
            for row in range(model.rowCount()):
                for column in range(model.columnCount()):
                    for role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
                        value = model.index(row, column).data(role)
                        if value:
                            texts.append(str(value))
            for column in range(model.columnCount()):
                header = model.headerData(column, Qt.Orientation.Horizontal)
                if header:
                    texts.append(str(header))
    return texts


def ui_findings(window, visible_only=True):
    texts = widget_texts(window, visible_only)
    for dialog in QApplication.topLevelWidgets():
        if dialog is not window and dialog.isVisible():
            texts += widget_texts(dialog, visible_only)
    return identifying_findings(texts)


def fake_011_core(path):
    """Answers exactly as task-core 0.1.1 does (from the recorded golden transcript); logs every request."""
    golden = json.loads((REPO / "tests" / "golden" / "v1_transcript_0.1.1.json").read_text())["transcript"]
    unsupported = next(e["reply"] for e in golden if e.get("send", "").startswith('{"v":3'))
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(8)
    received = []

    def handle(conn):
        buf = b""
        try:
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    request = json.loads(line)
                    received.append(request)
                    conn.sendall(json.dumps(dict(unsupported, id=request.get("id"))).encode() + b"\n")
        except OSError:
            pass
        finally:
            conn.close()

    def serve():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            threading.Thread(target=handle, args=(conn,), daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()
    return FakeOldCore(server, received)


class FakeOldCore:
    def __init__(self, server, received):
        self.server = server
        self.received = received

    def close(self):
        self.server.close()
