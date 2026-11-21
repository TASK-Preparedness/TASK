# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import pytest

from task_mesh.core.errors import ErrorCode, remedy_for
from task_mesh.domain.models import PortCandidate, RadioIdentity, StateSnapshot
from task_mesh.domain.states import ConnectionState as S
from task_mesh.ui.radio_panel import BUTTONS, RadioPanel
from tests.fakes.fake_ports import candidate

NOW = 1790000000
PORT = candidate("/dev/ttyUSB0", "/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0")
IDENT = RadioIdentity(0xA1B2C3D4, "!a1b2c3d4", "TASK Base", "TASK", "HELTEC_V3", None)


@pytest.fixture
def panel(qtbot):
    p = RadioPanel(now=lambda: NOW)
    qtbot.addWidget(p)
    p.resize(310, 560)
    p.show()
    return p


def plain(label):
    return label.text().replace("\u200b", "")


def test_connected_shows_device_and_port(panel):
    panel.render(StateSnapshot(state="CONNECTED", port=PORT, identity=IDENT))
    assert panel.badge.text() == "CONNECTED"
    t = panel.device_value.text()
    assert "TASK Base (TASK)" in t and "!a1b2c3d4" in t and "HELTEC_V3" in t and "Firmware: —" in t
    assert "usb-Silicon_Labs_CP2102" in plain(panel.port_value) and "/dev/ttyUSB0" in plain(panel.port_value)
    assert panel.disconnect_btn.isVisible() and panel.disconnect_btn.text() == "Disconnect"
    assert not panel.connect_btn.isVisible() and not panel.retry_btn.isVisible()


@pytest.mark.parametrize("state", [s for s in S if s not in (S.CONNECTED, S.CONNECTING, S.DEVICE_REBOOTING)])
def test_disconnected_badge_for_other_states(panel, state):
    panel.render(StateSnapshot(state=state.value))
    assert panel.badge.text() == "DISCONNECTED"
    assert state.value in panel.state_label.text()


@pytest.mark.parametrize("state", [S.CONNECTING, S.DEVICE_REBOOTING])
def test_connecting_badge(panel, state):
    panel.render(StateSnapshot(state=state.value, port=PORT))
    assert panel.badge.text() == "CONNECTING…"


@pytest.mark.parametrize("code", list(ErrorCode))
def test_remedy_text_for_every_error_code(panel, code):
    panel.render(StateSnapshot(state="BACKOFF", error_code=code.value, error_message="detail text",
                               error_at_local=NOW, retry_at_local=NOW + 4))
    assert panel.remedy_label.text() == remedy_for(code)
    assert "detail text" in plain(panel.error_value)
    assert "Retrying in 4 s" in panel.retry_label.text()


def test_permission_remedy_has_dialout_and_logout(panel):
    panel.render(StateSnapshot(state="PERMISSION_DENIED", error_code="PERMISSION_DENIED", error_message="x",
                               error_at_local=NOW))
    r = panel.remedy_label.text()
    assert "usermod -aG dialout" in r and "log out" in r
    assert panel.retry_btn.isVisible()


def test_no_error_shows_dash(panel):
    panel.render(StateSnapshot(state="IDLE"))
    assert panel.error_value.text() == "—" and panel.device_value.text() == "—" and panel.port_value.text() == "—"
    assert panel.connect_btn.isVisible()


def test_every_state_offers_at_least_one_action(panel):
    for st in S:
        panel.render(StateSnapshot(state=st.value))
        visible = [b for b in (panel.connect_btn, panel.retry_btn, panel.disconnect_btn, panel.rescan_btn)
                   if b.isVisible()]
        assert visible, st
        assert BUTTONS[st]


def test_picker_and_choice_signal(panel, qtbot):
    c2 = PortCandidate("/dev/ttyACM0", vid=0x303A, pid=0x1001, open_path="/dev/ttyACM0")
    panel.render(StateSnapshot(state="AWAITING_SELECTION", candidates=(PORT, c2)))
    assert panel.picker.isVisible() and panel.cand_list.count() == 2
    assert not panel.use_btn.isEnabled()
    panel.cand_list.setCurrentRow(1)
    panel.remember.setChecked(True)
    with qtbot.waitSignal(panel.candidate_chosen) as blocker:
        panel.use_btn.click()
    assert blocker.args == [c2, True]
    panel.render(StateSnapshot(state="CONNECTING", port=c2))
    assert not panel.picker.isVisible()


def test_buttons_emit_signals(panel, qtbot):
    panel.render(StateSnapshot(state="IDLE"))
    with qtbot.waitSignal(panel.connect_clicked):
        panel.connect_btn.click()
    panel.render(StateSnapshot(state="NO_DEVICE"))
    with qtbot.waitSignal(panel.rescan_clicked):
        panel.rescan_btn.click()
    with qtbot.waitSignal(panel.disconnect_clicked):
        panel.disconnect_btn.click()
    panel.render(StateSnapshot(state="BACKOFF"))
    with qtbot.waitSignal(panel.retry_clicked):
        panel.retry_btn.click()
