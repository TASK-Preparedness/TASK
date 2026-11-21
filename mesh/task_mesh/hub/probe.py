# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Read-only protocol identification for a serial radio.

Order: (1) a user assignment wins; (2) a cached probe result; (3) USB descriptor hints (no port access);
(4) an open-port probe: listen passively for frames, then at most ONE read-only query per protocol:
  * MeshCore companion: CMD_DEVICE_QUERY (0x16 0x03) framed '<' len16  -> answer framed '>' len16, code 13.
  * Meshtastic: the stream wake + ToRadio{want_config_id} the 0.2.0 connect already sends -> FromRadio 0x94 0xC3.
Neither query changes settings or transmits on the radio. Opening the port may toggle DTR/RTS (some ESP32
boards reset) — the same as 0.2.0. UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

MT_MAGIC = b"\x94\xc3"
MC_IN = 0x3E          # '>' device -> host
MC_DEVICE_QUERY = b"\x3c\x02\x00\x16\x03"
MC_RESP_DEVICE_INFO = 13
# Meshtastic: 4 x START2 wake-up bytes, then ToRadio{want_config_id: 0x5441534b} (field 3, varint)
MT_WANT_CONFIG = b"\xc3\xc3\xc3\xc3" + MT_MAGIC + b"\x00\x06" + b"\x18\xcb\xa6\x85\xa2\x05"
# Every byte string this module may ever write. Enforced by tests.
ALLOWED_WRITES = (MC_DEVICE_QUERY, MT_WANT_CONFIG)


def classify(data: bytes) -> Optional[str]:
    """Pure frame classifier on bytes read from the device."""
    i = data.find(MT_MAGIC)
    if i >= 0 and len(data) >= i + 4:
        n = int.from_bytes(data[i + 2:i + 4], "big")
        if 0 < n <= 512:
            return "meshtastic"
    j = 0
    while True:
        j = data.find(bytes([MC_IN]), j)
        if j < 0 or len(data) < j + 4:
            break
        n = int.from_bytes(data[j + 1:j + 3], "little")
        if 0 < n <= 300 and len(data) >= j + 3 + 1:
            code = data[j + 3]
            if code in (0, 1, 5, 13) or 0x80 <= code <= 0x90:   # OK/ERR/SELF_INFO/DEVICE_INFO/push codes
                return "meshcore"
        j += 1
    return None


def usb_hint(vid: Optional[int], pid: Optional[int], by_id_name: str) -> Optional[str]:
    """Descriptor-only hint. The USB bridges (CP210x, CH9102, ESP32-S3 CDC, nRF52) are shared by both firmwares,
    so only an explicit product string is trusted."""
    n = (by_id_name or "").lower()
    if "meshtastic" in n:
        return "meshtastic"
    if "meshcore" in n:
        return "meshcore"
    return None


class SerialLike:
    def read(self, n: int) -> bytes: ...
    def write(self, b: bytes) -> int: ...
    def reset_input_buffer(self) -> None: ...
    def close(self) -> None: ...


def probe_port(open_port: Callable[[], SerialLike], listen_s: float = 1.5, answer_s: float = 2.0,
               clock=time.monotonic, active: bool = True) -> tuple[Optional[str], str]:
    """-> (protocol | None, how). Opens, reads, writes only ALLOWED_WRITES, closes."""
    port = open_port()
    try:
        buf = b""
        end = clock() + listen_s
        while clock() < end:
            buf += port.read(256) or b""
            p = classify(buf)
            if p:
                return p, "passive"
        if not active:
            return None, "passive-silent"
        for query, proto in ((MC_DEVICE_QUERY, "meshcore"), (MT_WANT_CONFIG, "meshtastic")):
            assert query in ALLOWED_WRITES
            port.reset_input_buffer()
            port.write(query)
            buf = b""
            end = clock() + answer_s
            while clock() < end:
                buf += port.read(256) or b""
                p = classify(buf)
                if p:
                    return p, f"query:{proto}"
        return None, "no-answer"
    finally:
        port.close()
