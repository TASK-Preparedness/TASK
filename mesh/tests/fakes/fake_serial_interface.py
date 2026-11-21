# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Imitates the parts of meshtastic.serial_interface.SerialInterface that MeshtasticProvider touches.

Publishes REAL pypubsub topics from a thread named 'publishing' (like the library)."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any, Optional

from pubsub import pub


class FakeSerialInterface:
    raise_on_init: Optional[BaseException] = None
    instances: list["FakeSerialInterface"] = []
    calls: list[dict] = []

    def __init__(self, devPath: Optional[str] = None, timeout: int = 300, **kw: Any) -> None:  # noqa: N803
        FakeSerialInterface.calls.append({"devPath": devPath, "timeout": timeout, **kw})
        if devPath is None:
            raise AssertionError("devPath=None must never be passed")
        if FakeSerialInterface.raise_on_init is not None:
            raise FakeSerialInterface.raise_on_init
        self.devPath = devPath
        self.myInfo = SimpleNamespace(my_node_num=0xA1B2C3D4)
        self.metadata = SimpleNamespace(firmware_version="2.7.15.567b8ea")
        self.nodesByNum: dict[int, dict] = {
            0xA1B2C3D4: {"num": 0xA1B2C3D4, "user": {"id": "!a1b2c3d4", "longName": "TASK Base",
                                                    "shortName": "TASK", "hwModel": "HELTEC_V3"}},
            0x55667788: {"num": 0x55667788, "user": {"id": "!55667788", "longName": "Meshtastic 7788",
                                                    "shortName": "7788", "hwModel": "UNSET"}},
        }
        self.isConnected = threading.Event()
        self.isConnected.set()
        self.stream = object()
        self._stop = threading.Event()
        self._rxThread = threading.Thread(target=self._stop.wait, name="stream reader", daemon=True)
        self._rxThread.start()
        self.closed = False
        self.heartbeats = 0
        FakeSerialInterface.instances.append(self)
        self.publish("meshtastic.connection.established", interface=self)

    def publish(self, topic: str, **kw: Any) -> None:
        t = threading.Thread(target=lambda: pub.sendMessage(topic, **kw), name="publishing", daemon=True)
        t.start()
        t.join(2)

    def sendHeartbeat(self) -> None:  # noqa: N802
        self.heartbeats += 1

    sent_texts: list = []
    _next_id = 0x1000

    def sendText(self, text, destinationId=0xFFFFFFFF, wantAck=False, channelIndex=0, **kw):  # noqa: N802,N803
        FakeSerialInterface._next_id += 1
        pid = FakeSerialInterface._next_id
        self.sent_texts.append({"text": text, "dest": destinationId, "wantAck": wantAck, "channel": channelIndex,
                                "id": pid})
        return SimpleNamespace(id=pid)

    @property
    def localNode(self):  # noqa: N802
        def ch(index, role, name, psk=b"\x01SECRETKEY"):
            return SimpleNamespace(index=index, role=role, settings=SimpleNamespace(name=name, psk=psk))
        return SimpleNamespace(channels=[ch(0, 1, ""), ch(1, 2, "Ops"), ch(2, 0, "")])

    def unplug(self) -> None:
        self._stop.set()
        self._rxThread.join(1)
        self.stream = None
        self.isConnected.clear()
        self.publish("meshtastic.connection.lost", interface=self)

    def close(self) -> None:
        self.closed = True
        self._stop.set()
        self.stream = None
        time.sleep(0)

    @classmethod
    def reset(cls) -> None:
        cls.raise_on_init = None
        cls.instances = []
        cls.calls = []
        cls.sent_texts = []
