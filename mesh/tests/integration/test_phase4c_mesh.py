# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-mesh 0.2.0 integration: legacy data copy, status card, Maps feed opt-in, Messages panel (offscreen)."""

import json
import stat
from types import SimpleNamespace

import pytest

from task_comms.auth import SessionGate
from task_comms.feeds import FeedWriter, read_feed
from task_comms.status import StatusWriter, read_status
from task_mesh.domain.models import NodeRecord
from task_mesh.messaging.service import MessageService
from task_mesh.messaging.store import MessageStore
from task_mesh.services.integration import MapFeed, StatusCard, copy_legacy_dirs
from tests.unit.test_messaging import FakeClient


def test_mi01_legacy_dirs_copied_never_moved(tmp_path):
    old = tmp_path / "share/rain-mesh"
    old.mkdir(parents=True)
    (old / "rain-mesh.sqlite3").write_bytes(b"db")
    new = tmp_path / "share/task-mesh"
    assert copy_legacy_dirs([new]) == [str(old)]
    assert (old / "rain-mesh.sqlite3").read_bytes() == b"db"      # legacy untouched
    assert (new / "task-mesh.sqlite3").read_bytes() == b"db"
    assert stat.S_IMODE(new.stat().st_mode) == 0o700
    (new / "task-mesh.sqlite3").write_bytes(b"newer")
    assert copy_legacy_dirs([new]) == []                           # never overwrites existing data
    assert (new / "task-mesh.sqlite3").read_bytes() == b"newer"


def test_mi02_status_card_has_no_content(tmp_path):
    card = StatusCard(StatusWriter("task-mesh", tmp_path))
    card.nodes, card.unread = 3, 2
    card.on_state(SimpleNamespace(state="CONNECTED", identity=SimpleNamespace(short_name="BASE", node_id="!a1"),
                                  error_code=None))
    doc = read_status(tmp_path / "task-mesh.json")
    assert doc["state"] == "connected" and doc["device"] == "BASE" and doc["counts"] == {"nodes": 3, "unread": 2}
    assert "text" not in json.dumps(doc).lower()


def _rec(num, lat=40.27, lon=-76.88, mqtt=False):
    return NodeRecord(node_num=num, first_seen_local=1, updated_local=2, node_id=f"!{num:08x}", short_name="N",
                      latitude=lat, longitude=lon, last_rx_local=1700000000, via_mqtt=mqtt)


def test_mi03_map_feed_opt_in_and_cleared(tmp_path):
    feed = MapFeed(lambda: FeedWriter("task-mesh", tmp_path))
    feed.update(_rec(1))
    assert not (tmp_path / "task-mesh.sqlite").exists()            # nothing written while off (default)
    feed.set_enabled(True, [_rec(1), _rec(2, lat=None, lon=None), _rec(3, mqtt=True)])
    _, rows = read_feed(tmp_path / "task-mesh.sqlite")
    assert sorted((r["id"], r["source"]) for r in rows) == [("mesh:!00000001", "mesh"), ("mesh:!00000003", "mesh-mqtt")]
    feed.set_enabled(False)
    assert read_feed(tmp_path / "task-mesh.sqlite")[1] == []


def test_mi04_messages_panel_locked_then_send(qtbot, tmp_path):
    from task_mesh.ui.messages_panel import MessagesPanel
    sent = []
    gate = SessionGate(FakeClient())
    svc = MessageService(MessageStore(tmp_path / "m.sqlite3"), gate, lambda t, d, c: sent.append((t, d, c)) or 42,
                         run_async=lambda fn: fn())
    panel = MessagesPanel(svc, lambda: [(0, "Primary", "PRIMARY"), (1, "Ops", "SECONDARY")],
                          lambda: [("!11223344", "Bob")])
    qtbot.addWidget(panel)
    assert not panel.compose.isEnabled() and panel.locked_note.isVisibleTo(panel)
    assert [panel.conv.itemText(i) for i in range(panel.conv.count())] == [
        "Channel 0: Primary", "Channel 1: Ops", "DM Bob (!11223344)"]
    gate.sign_in("op", "pw")
    svc.unlock()
    panel._apply_lock()
    panel.conv.setCurrentIndex(2)
    panel.compose.setText("hello bob")
    panel.send()
    qtbot.waitUntil(lambda: panel.list.count() == 1)
    assert sent == [("hello bob", 0x11223344, 0)] and "sent (no ACK yet)" in panel.list.item(0).text()
    gate.session_ended("session-ended")
    qtbot.waitUntil(lambda: not panel.compose.isEnabled())
    assert panel.list.count() == 0
