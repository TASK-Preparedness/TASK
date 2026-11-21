# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Discovery matrix (AT-03) with fake comports() and a temporary /dev/serial tree."""

import os

import pytest

from task_mesh.core.errors import ErrorCode
from task_mesh.domain.models import Classification
from task_mesh.radio.discovery import ChoiceKind, choose_candidate, enumerate_ports, is_busy_error, preflight
from tests.fakes.fake_ports import ESP32S3, FTDI, HELTEC, UBLOX, FakePortInfo, make_tree

BYID_HELTEC = "usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0"


def enum(tmp_path, ports, links):
    root = make_tree(tmp_path / "serial", links)
    return enumerate_ports(comports=lambda: ports, serial_dir=root)


def test_single_heltec_uses_by_id(tmp_path):
    c = enum(tmp_path, [FakePortInfo("/dev/ttyUSB0", **HELTEC)],
             {"by-id": {BYID_HELTEC: "/dev/ttyUSB0"}, "by-path": {"platform-xhci-usb-0:1:1.0-port0": "/dev/ttyUSB0"}})
    assert len(c) == 1
    assert c[0].classification is Classification.LIKELY
    assert c[0].open_path.endswith(BYID_HELTEC)
    ch = choose_candidate(c)
    assert ch.kind is ChoiceKind.AUTO and ch.candidate == c[0]


def test_never_assumes_ttyusb0_and_supports_acm(tmp_path):
    c = enum(tmp_path, [FakePortInfo("/dev/ttyACM3", **ESP32S3)], {})
    assert c[0].device == "/dev/ttyACM3" and c[0].open_path == "/dev/ttyACM3"
    assert choose_candidate(c).kind is ChoiceKind.AUTO


def test_heltec_plus_gps_autoconnects_heltec(tmp_path):
    c = enum(tmp_path, [FakePortInfo("/dev/ttyACM0", **UBLOX), FakePortInfo("/dev/ttyUSB0", **HELTEC)],
             {"by-id": {BYID_HELTEC: "/dev/ttyUSB0"}})
    gps = next(x for x in c if x.device == "/dev/ttyACM0")
    assert gps.classification is Classification.NEVER
    ch = choose_candidate(c)
    assert ch.kind is ChoiceKind.AUTO and ch.candidate.device == "/dev/ttyUSB0"
    assert gps not in ch.candidates


def test_heltec_plus_esp32s3_requires_selection_but_lists_heltec(tmp_path):
    c = enum(tmp_path, [FakePortInfo("/dev/ttyUSB0", **HELTEC), FakePortInfo("/dev/ttyACM0", **ESP32S3)], {})
    ch = choose_candidate(c)
    assert ch.kind is ChoiceKind.SELECT and ch.candidate is None
    assert {x.device for x in ch.candidates} == {"/dev/ttyUSB0", "/dev/ttyACM0"}


def test_two_cp2102_same_serial_fall_back_to_by_path(tmp_path):
    # udev creates ONE by-id link for both boards (same serial 0001): it must not be trusted.
    c = enum(tmp_path, [FakePortInfo("/dev/ttyUSB0", **HELTEC), FakePortInfo("/dev/ttyUSB1", **HELTEC)],
             {"by-id": {BYID_HELTEC: "/dev/ttyUSB1"},
              "by-path": {"platform-usb-0:1:1.0-port0": "/dev/ttyUSB0", "platform-usb-0:2:1.0-port0": "/dev/ttyUSB1"}})
    assert all(x.ambiguous_by_id for x in c)
    assert [x.open_path.rsplit("/", 1)[-1] for x in c] == ["platform-usb-0:1:1.0-port0", "platform-usb-0:2:1.0-port0"]
    assert choose_candidate(c).kind is ChoiceKind.SELECT


def test_ports_without_vid_or_non_usb_ignored(tmp_path):
    c = enum(tmp_path, [FakePortInfo("/dev/ttyS0"), FakePortInfo("/dev/ttyUSB0"), FakePortInfo("/dev/ttyAMA0", vid=1)],
             {})
    assert c == []
    assert choose_candidate(c).kind is ChoiceKind.NONE


def test_unknown_usb_serial_is_possible_and_needs_selection(tmp_path):
    c = enum(tmp_path, [FakePortInfo("/dev/ttyUSB0", **FTDI)], {})
    assert c[0].classification is Classification.POSSIBLE
    assert choose_candidate(c).kind is ChoiceKind.SELECT


def test_pinned_device_present_and_absent(tmp_path):
    ports = [FakePortInfo("/dev/ttyUSB0", **HELTEC), FakePortInfo("/dev/ttyACM0", **ESP32S3)]
    c = enum(tmp_path, ports, {"by-id": {BYID_HELTEC: "/dev/ttyUSB0"}})
    heltec = next(x for x in c if x.device == "/dev/ttyUSB0")
    ch = choose_candidate(c, pinned=heltec.identity())
    assert ch.kind is ChoiceKind.AUTO and ch.candidate == heltec and ch.why == "pinned device"
    absent = {"by_id": "/dev/serial/by-id/usb-other", "vid": 0x1A86, "pid": 0x55D4, "serial": "X"}
    assert choose_candidate(c, pinned=absent).kind is ChoiceKind.SELECT


def test_last_success_breaks_tie(tmp_path):
    ports = [FakePortInfo("/dev/ttyUSB0", **HELTEC), FakePortInfo("/dev/ttyACM0", **ESP32S3)]
    c = enum(tmp_path, ports, {})
    esp = next(x for x in c if x.device == "/dev/ttyACM0")
    ch = choose_candidate(c, last_success=esp.identity())
    assert ch.kind is ChoiceKind.AUTO and ch.candidate == esp


def test_comports_failure_returns_empty():
    def boom():
        raise OSError("sysfs gone")
    assert enumerate_ports(comports=boom) == []


def test_preflight_missing_and_ok(tmp_path):
    assert preflight(str(tmp_path / "nope")).code is ErrorCode.NO_DEVICE
    f = tmp_path / "dev"
    f.write_text("")
    assert preflight(str(f)).ok


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses permission bits")
def test_preflight_permission_denied_has_hint(tmp_path):
    f = tmp_path / "ttyUSB9"
    f.write_text("")
    f.chmod(0)
    try:
        pf = preflight(str(f))
        assert not pf.ok and pf.code is ErrorCode.PERMISSION_DENIED
        assert "group" in pf.message
    finally:
        f.chmod(0o600)


def test_busy_error_detection():
    import errno

    assert is_busy_error(Exception("[Errno 11] Could not exclusively lock port /dev/ttyUSB0"))
    assert is_busy_error(OSError(errno.EBUSY, "busy"))
    assert not is_busy_error(OSError(errno.ENOENT, "missing"))
