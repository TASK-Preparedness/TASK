# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import pytest

pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from fake_direwolf import FakeAgw  # noqa: E402
from test_aprs import setup, wait  # noqa: E402


class Gate:
    def __init__(self, role=None):
        self.role, self.listeners = role, []

    @property
    def unlocked(self):
        return self.role is not None

    def require(self, role="operator"):
        if self.role is None:
            return False, "sign in required"
        return (True, "") if role != "administrator" or self.role == "administrator" else (False, "administrator role required")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_window_no_tx_on_start_and_locked_send(tmp_path, app, monkeypatch):
    from task_aprs.ui.main_window import MainWindow
    agw = FakeAgw()
    try:
        svc, _ = setup(tmp_path, agw_port=agw.port)
        svc.connect()
        msgs = []
        monkeypatch.setattr(QMessageBox, "information", lambda *a: msgs.append(a[2]))
        w = MainWindow(svc, Gate(None))
        w._tick()
        w.to.setText("N0DST")
        w.text.setText("hello")
        w.send_btn.click()
        assert msgs == ["sign in required"] and agw.frames == []
        assert "N0TST>APZTSK" in w.preview.text()
        w.gate = Gate("operator")
        w.send_btn.click()
        assert wait(lambda: len(agw.frames) == 1)
        w._refresh(None)
        assert w.outbox.item(0, 2).text() == "submitted" and w.queued_label.text() == "QUEUED"
        w.save_settings()
        assert "administrator" in msgs[-1]
        w.close()
    finally:
        agw.close()
