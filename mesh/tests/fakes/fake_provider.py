# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Scriptable RadioProvider for service/UI tests. Emits through the sink from its own thread."""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

from task_mesh.core.errors import ErrorCode
from task_mesh.domain.models import (
    MetricsData,
    NodeInfoData,
    Observation,
    PortCandidate,
    PositionData,
    RadioIdentity,
    UserData,
)
from task_mesh.radio.base import ConnectError

LOCAL = RadioIdentity(node_num=0xA1B2C3D4, node_id="!a1b2c3d4", long_name="TASK Base", short_name="TASK",
                      hw_model="HELTEC_V3", firmware_version="2.7.15.567b8ea")


def sample_nodes() -> list[NodeInfoData]:
    return [
        NodeInfoData(0xA1B2C3D4, UserData("!a1b2c3d4", "TASK Base", "TASK", "HELTEC_V3"),
                     metrics=MetricsData(101, 4.9)),
        NodeInfoData(0x11223344, UserData("!11223344", "Ridge Relay", "RDG", "RAK4631", "ROUTER"),
                     PositionData(40.1234567, -105.1234567), MetricsData(87), snr=6.25,
                     last_heard_radio=1759600000, hops_away=2),
        NodeInfoData(0x55667788, UserData("!55667788")),
    ]


class Script:
    """Shared, mutable behaviour for every provider instance a factory creates."""

    def __init__(self) -> None:
        self.connect_errors: list[Optional[ConnectError]] = []  # consumed per attempt; None = success
        self.connect_delay = 0.0
        self.block_forever = threading.Event()  # set() to make connect hang until released
        self.release = threading.Event()
        self.identity = LOCAL
        self.nodes = sample_nodes()
        self.attempts: list[PortCandidate] = []
        self.heartbeat_error: Optional[BaseException] = None


class FakeRadioProvider:
    def __init__(self, sink: Any, script: Script) -> None:
        self.sink = sink
        self.script = script
        self.gen: Optional[int] = None
        self.alive = False
        self.open = False
        self.closed = False
        self.heartbeats = 0
        self.counters = {"packets": 0}

    @property
    def current_generation(self) -> Optional[int]:
        return self.gen

    def connect(self, candidate: PortCandidate, generation: int) -> RadioIdentity:
        s = self.script
        s.attempts.append(candidate)
        self.gen = generation
        if s.block_forever.is_set():
            s.release.wait(120)
        if s.connect_delay:
            time.sleep(s.connect_delay)
        err = s.connect_errors.pop(0) if s.connect_errors else None
        if err is not None:
            raise err
        for n in s.nodes:
            self.sink.on_nodeinfo(generation, n)
        self.alive = self.open = True
        self.sink.on_established(generation)
        return s.identity

    def snapshot_nodes(self) -> list[NodeInfoData]:
        return list(self.script.nodes)

    def is_alive(self) -> bool:
        return self.alive

    def port_open(self) -> bool:
        return self.open

    def send_heartbeat(self) -> None:
        self.heartbeats += 1
        if self.script.heartbeat_error is not None:
            raise self.script.heartbeat_error

    def close(self) -> None:
        self.closed = True
        self.alive = self.open = False

    shutdown = close

    # ----- scripted events (run on a separate thread like the library's publisher) ---------------
    def _later(self, fn, *a) -> threading.Thread:
        t = threading.Thread(target=fn, args=a, name="publishing", daemon=True)
        t.start()
        return t

    def emit_packet(self, obs: Observation) -> threading.Thread:
        return self._later(self.sink.on_observation, self.gen, obs)

    def emit_node(self, info: NodeInfoData) -> threading.Thread:
        return self._later(self.sink.on_nodeinfo, self.gen, info)

    def drop(self) -> threading.Thread:
        """Unplug: reader dies, stream closed, lost published."""
        self.alive = self.open = False
        return self._later(self.sink.on_lost, self.gen)

    def reboot(self, come_back_after: Optional[float] = 0.3) -> threading.Thread:
        def run() -> None:
            self.sink.on_lost(self.gen)
            if come_back_after is not None:
                time.sleep(come_back_after)
                self.sink.on_established(self.gen)
        return self._later(run)

    def flood(self, n: int, rate: float, now: int = 1790000000) -> threading.Thread:
        def run() -> None:
            interval = 1.0 / rate
            t0 = time.monotonic()
            for i in range(n):
                self.sink.on_observation(self.gen, Observation(
                    node_num=0x1000 + (i % 200), observed_local=now, rx_rssi=-80 - (i % 30), rx_snr=5.0,
                    portnum="TEXT_MESSAGE_APP"))
                delay = t0 + (i + 1) * interval - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
        return self._later(run)


class ProviderFactory:
    """provider_factory(sink) for RadioWorker; remembers every instance."""

    def __init__(self, script: Optional[Script] = None) -> None:
        self.script = script or Script()
        self.instances: list[FakeRadioProvider] = []

    def __call__(self, sink: Any) -> FakeRadioProvider:
        p = FakeRadioProvider(sink, self.script)
        self.instances.append(p)
        return p

    @property
    def last(self) -> FakeRadioProvider:
        return self.instances[-1]


def err(code: ErrorCode, msg: str = "scripted") -> ConnectError:
    return ConnectError(code, msg)
