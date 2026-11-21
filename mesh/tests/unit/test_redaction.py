# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""AT-21: key material never reaches log files (or the DB), even with the app at DEBUG."""

import base64
import json
import logging
import os

import pytest

from task_mesh.core.logging_setup import REDACTED, RedactingFilter, redact_text, setup_logging

ASCII_PSK = b"SECRETKEY-0123456789abcdef012345"
RANDOM_PSK = bytes.fromhex("d4f1bb3a20290759f0bcffabcf4e6901d4f1bb3a20290759f0bcffabcf4e6901")


def _channel_frame(psk: bytes) -> bytes:
    from meshtastic.protobuf import channel_pb2, mesh_pb2

    f = mesh_pb2.FromRadio()
    f.channel.index = 0
    f.channel.role = channel_pb2.Channel.Role.PRIMARY
    f.channel.settings.psk = psk
    f.channel.settings.name = "OPS"
    return f.SerializeToString()


def _needles(psk: bytes) -> list[str]:
    out = [base64.b64encode(psk).decode(), psk.hex()]
    if psk.isascii():
        out.append(psk.decode())
    return out


@pytest.mark.parametrize("text", [
    "channel settings psk: 'abc'", "session_passkey=xyz", "publicKey: 'AAAA'", "private_key set",
])
def test_messages_naming_keys_are_dropped(text):
    assert redact_text(text) == REDACTED


def test_blobs_redacted_paths_kept():
    assert "[REDACTED" in redact_text("bytes b'\\x01\\x02\\x03\\x04\\x05\\x06\\x07\\x08\\x09\\x0a\\x0b\\x0c\\x0d\\x0e\\x0f\\x10'")
    assert "[REDACTED" in redact_text("blob 1PG7OiApB1nwvP+rz05pAQ==")
    assert "[REDACTED" in redact_text("hex " + RANDOM_PSK.hex())
    assert redact_text("opening /dev/serial/by-id/usb-Silicon_Labs_CP2102-if00-port0") == \
        "opening /dev/serial/by-id/usb-Silicon_Labs_CP2102-if00-port0"


def test_filter_redacts_args_and_exceptions():
    rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "value %s", (base64.b64encode(RANDOM_PSK).decode(),), None)
    try:
        raise ValueError(f"bad {RANDOM_PSK.hex()}")
    except ValueError:
        import sys

        rec.exc_info = sys.exc_info()
    RedactingFilter().filter(rec)
    assert base64.b64encode(RANDOM_PSK).decode() not in rec.getMessage()
    assert RANDOM_PSK.hex() not in (rec.exc_text or "")


@pytest.mark.parametrize("psk", [ASCII_PSK, RANDOM_PSK])
def test_library_debug_output_never_reaches_log_file(tmp_path, psk):
    from meshtastic.mesh_interface import MeshInterface

    log_file = tmp_path / "log" / "task-mesh.jsonl"
    setup_logging(log_file, "DEBUG", console=False)
    iface = MeshInterface(noProto=True)
    iface._localChannels = []
    try:
        iface._handleFromRadio(_channel_frame(psk))          # clamped: library at WARNING
        logging.getLogger("meshtastic").setLevel(logging.DEBUG)  # worst case: someone unclamps it
        iface._handleFromRadio(_channel_frame(psk))
        logging.getLogger("task_mesh.test").debug("extra field test", extra={"detail": base64.b64encode(psk).decode()})
    finally:
        logging.getLogger("meshtastic").setLevel(logging.WARNING)
        iface.close()
    for h in logging.getLogger().handlers:
        h.flush()
    text = log_file.read_text(encoding="utf-8")
    assert text.strip(), "expected log lines"
    for line in text.splitlines():
        json.loads(line)
    for needle in _needles(psk):
        assert needle not in text
    # also not in any repr form of the raw frame
    assert repr(_channel_frame(psk))[2:-1] not in text


def test_library_logger_clamped_after_setup(tmp_path):
    setup_logging(tmp_path / "x.jsonl", "DEBUG", console=False)
    assert logging.getLogger("meshtastic").level == logging.WARNING
    assert logging.getLogger().level == logging.DEBUG


def test_log_file_permissions_private(tmp_path):
    setup_logging(tmp_path / "logs" / "a.jsonl", "INFO", console=False)
    assert oct(os.stat(tmp_path / "logs").st_mode & 0o077) == "0o0"
