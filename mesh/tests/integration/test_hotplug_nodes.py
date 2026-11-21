# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Hot-plug watchers (udev + polling fallback) and NodeService coalescing."""

import time

from task_mesh.domain.models import NodeInfoData, Observation, UserData
from task_mesh.radio import hotplug
from task_mesh.radio.hotplug import PollingHotplugWatcher, create_hotplug_watcher
from task_mesh.services.node_service import NodeService


def test_polling_watcher_debounced_change(qtbot):
    sig = {"v": ("a",)}
    w = PollingHotplugWatcher(lambda: sig["v"], interval_ms=50, debounce_ms=100)
    got = []
    w.changed.connect(got.append)
    w.start()
    qtbot.wait(150)
    assert got == []
    sig["v"] = ("a", "b")
    qtbot.waitUntil(lambda: got == ["poll_change"], timeout=1000)
    sig["v"] = ("b",)
    qtbot.wait(20)
    sig["v"] = ("c",)
    qtbot.wait(400)
    assert len(got) <= 3
    w.stop()


def test_fallback_to_polling_without_udevd(qtbot, monkeypatch):
    monkeypatch.setattr(hotplug, "udevd_running", lambda: False)
    assert create_hotplug_watcher().mode == "polling"


def test_udev_watcher_when_available(qtbot, monkeypatch):
    monkeypatch.setattr(hotplug, "udevd_running", lambda: True)
    w = create_hotplug_watcher()
    assert w.mode in ("udev", "polling")  # polling if libudev/netlink unavailable
    if w.mode == "udev":
        class Dev:
            action = "add"
            device_node = "/dev/ttyUSB3"

        got = []
        w.changed.connect(got.append)
        w._on_event(Dev())
        Dev.device_node = "/dev/ttyS0"
        w._on_event(Dev())
        qtbot.waitUntil(lambda: got == ["hotplug_add"], timeout=2000)


def test_udev_failure_falls_back(qtbot, monkeypatch):
    monkeypatch.setattr(hotplug, "udevd_running", lambda: True)

    def boom(*a, **k):
        raise OSError("no netlink")

    monkeypatch.setattr(hotplug, "UdevHotplugWatcher", boom)
    assert create_hotplug_watcher().mode == "polling"


def test_node_service_coalesces_and_persists(qtbot):
    ops = []
    ns = NodeService(record=lambda op, *a: ops.append(op) or True, now=lambda: 1790000000, coalesce_ms=100)
    batches = []
    ns.rows_changed.connect(batches.append)
    counts = []
    ns.counts_changed.connect(lambda a, b: counts.append((a, b)))
    for i in range(300):
        ns.on_observation(Observation(10 + i % 5, 1790000000, rx_rssi=-90))
    ns.on_nodeinfo(NodeInfoData(99, UserData("!00000063", "N")))
    qtbot.waitUntil(lambda: bool(batches), timeout=1000)
    qtbot.wait(200)
    assert len(batches) == 1 and len(batches[0]) == 6
    assert counts[-1] == (6, 6)
    assert ops.count("obs") == 300 and ops.count("node") == 301


def test_node_service_persisted_are_stale_not_session(qtbot):
    from task_mesh.domain.models import NodeRecord

    ns = NodeService(coalesce_ms=50)
    counts = []
    ns.counts_changed.connect(lambda a, b: counts.append((a, b)))
    ns.load_persisted([NodeRecord(1, 0, 0, long_name="old")])
    assert counts[-1] == (1, 0) and ns.nodes[1].stale
    ns.on_observation(Observation(1, 1790000000))
    qtbot.waitUntil(lambda: counts[-1] == (1, 1), timeout=1000)
    assert not ns.nodes[1].stale and ns.nodes[1].long_name == "old"
