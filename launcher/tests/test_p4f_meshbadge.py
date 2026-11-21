# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4F: Mesh tile badge is read-only; all 12 tiles (incl. task.medical, task.library) survive."""
import hashlib
import json
import os
import socket
import sqlite3
import threading

from test_registry_tiles import BUILTIN_KEYS, make_registry

from task_launcher.services import meshbadge
from task_launcher.services.readiness import ProbeResults as Probes

DDL = ("CREATE TABLE notification(id INTEGER PRIMARY KEY, source TEXT, message_id TEXT, conversation TEXT, "
       "sender TEXT, sender_label TEXT, channel_label TEXT, preview TEXT, received_at REAL, origin TEXT, "
       "priority TEXT, priority_reason TEXT, read INTEGER, read_at REAL)")


def _store(tmp_path):
    p = tmp_path / "notifications.sqlite"
    db = sqlite3.connect(p)
    db.execute(DDL)
    rows = [("mesh.meshtastic", 0, None), ("mesh.meshtastic", 0, "alert"), ("mesh.meshcore", 0, None),
            ("mesh.meshcore", 1, None), ("aprs", 0, None)]
    for i, (src, rd, pr) in enumerate(rows):
        db.execute("INSERT INTO notification(source, message_id, conversation, read, priority) VALUES(?,?,?,?,?)",
                   (src, str(i), "c", rd, pr))
    db.commit()
    db.close()
    os.chmod(p, 0o600)
    return p


def _digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest(), os.stat(p).st_mode


def test_badge_from_store_is_read_only_and_correct(tmp_path):
    p = _store(tmp_path)
    before = _digest(p)
    for _ in range(3):
        b = meshbadge.from_store(p)
    assert b == {"total": 3, "priority": 1, "by_protocol": {"meshtastic": 2, "meshcore": 1}, "source": "store"}
    assert _digest(p) == before
    assert meshbadge.badge_text(b) == "3 unread (Meshtastic 2 · MeshCore 1) · ! 1 priority"


def test_badge_from_service_socket_uses_only_unread_query(tmp_path):
    path = tmp_path / "mesh.sock"
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(path))
    srv.listen(1)
    seen = []

    def serve():
        c, _ = srv.accept()
        seen.append(json.loads(c.recv(4096).split(b"\n")[0]))
        c.sendall(json.dumps({"id": 1, "ok": True, "result": {"total": 2, "priority": 0, "by_protocol": {
            "meshtastic": {"unread": 0}, "meshcore": {"unread": 2}}}}).encode() + b"\n")
        c.close()
    t = threading.Thread(target=serve, daemon=True)
    t.start()
    b = meshbadge.from_service(path, timeout=2)
    t.join(2)
    srv.close()
    assert seen[0]["method"] == "unread"
    assert b["total"] == 2 and meshbadge.badge_text(b) == "2 unread (MeshCore 2)"


def test_no_badge_when_nothing_unread_or_no_source(tmp_path):
    assert meshbadge.collect(tmp_path / "none.sock", tmp_path / "none.sqlite") is None
    assert meshbadge.badge_text({"total": 0, "by_protocol": {}}) is None


def test_mesh_readiness_line_shows_badge():
    pr = Probes()
    pr.mesh_badge = {"total": 1, "priority": 0, "by_protocol": {"meshtastic": 1, "meshcore": 0}}
    assert pr.line("mesh", None).text.startswith("1 unread (Meshtastic 1)")


def test_all_twelve_tiles_and_medical_id_preserved(tmp_path):
    reg = make_registry(tmp_path)
    keys = [t.key for t in reg.visible()]
    assert keys == BUILTIN_KEYS and len(keys) == 12
    assert "app:task.medical" in keys and "app:task.library" in keys
