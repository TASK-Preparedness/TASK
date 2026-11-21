# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4E groundwork: notification-source API with simulated Meshtastic packets (no radio, no TX)."""

import ast
import os
from pathlib import Path

import pytest

from task_comms import notifications as nt

ME = 0x11111111
ALICE = 0xA1B2C3D4


def pkt(pid, text="hello", frm=ALICE, to=0xFFFFFFFF, channel=0, priority=None, port="TEXT_MESSAGE_APP"):
    p = {"id": pid, "from": frm, "to": to, "channel": channel, "rxTime": 1760000000 + pid,
         "decoded": {"portnum": port, "text": text}}
    if priority is not None:
        p["priority"] = priority
    return p


@pytest.fixture
def store(tmp_path):
    s = nt.NotificationStore(tmp_path / "n.sqlite")
    yield s
    s.close()


def rec(store, p, **kw):
    n = nt.from_meshtastic(p, ME, **kw)
    return n, (store.record(n) if n else None)


def test_m01_live_message_counts_unread_per_conversation(store):
    rec(store, pkt(1))
    rec(store, pkt(2, channel=1))
    rec(store, pkt(3, to=ME))
    u = store.unread("mesh")
    assert set(u) == {"ch:0", "ch:1", "dm:!a1b2c3d4"} and all(c["count"] == 1 for c in u.values())
    assert store.badge("mesh") == {"unread": 3, "priority": 0, "conversations": 3}


def test_m02_unread_persists_across_restart(tmp_path):
    s = nt.NotificationStore(tmp_path / "n.sqlite")
    rec(s, pkt(10))
    s.close()
    s2 = nt.NotificationStore(tmp_path / "n.sqlite")
    assert s2.badge("mesh")["unread"] == 1
    assert oct(os.stat(tmp_path / "n.sqlite").st_mode & 0o777) == "0o600"
    s2.close()


def test_m03_packet_id_dedupe(store):
    _, first = rec(store, pkt(42))
    _, again = rec(store, pkt(42))          # same packet heard twice (rebroadcast / reconnect replay)
    assert first is True and again is False and store.badge("mesh")["unread"] == 1


def test_m04_history_sync_is_not_new(store):
    _, new = rec(store, pkt(5), origin=nt.HISTORY)
    assert new is False and store.badge("mesh")["unread"] == 0 and store.count_all("mesh") == 1
    _, live_again = rec(store, pkt(5))      # the same packet arriving live later is still a duplicate
    assert live_again is False


def test_m05_preview_does_not_mark_read(store):
    rec(store, pkt(7, "water point at grid 4"))
    for _ in range(3):
        u = store.unread("mesh")
    assert u["ch:0"]["last_preview"] == "water point at grid 4" and u["ch:0"]["count"] == 1


def test_m06_mark_read_per_conversation(store):
    rec(store, pkt(1))
    rec(store, pkt(2, to=ME))
    assert store.mark_read("mesh", "ch:0") == 1
    assert set(store.unread("mesh")) == {"dm:!a1b2c3d4"}


def test_m07_mark_all_needs_confirmation_and_never_erases(store):
    for i in range(1, 4):
        rec(store, pkt(i, channel=i))
    with pytest.raises(nt.ConfirmationRequired):
        store.mark_all_read("mesh")
    assert store.badge("mesh")["unread"] == 3
    assert store.mark_all_read("mesh", confirm=True) == 3
    assert store.badge("mesh")["unread"] == 0 and store.count_all("mesh") == 3      # nothing deleted
    assert not any(hasattr(store, m) for m in ("delete", "purge", "clear"))


def test_m08_priority_only_from_protocol_or_user_rule(store):
    n, _ = rec(store, pkt(1, "URGENT SOS mayday emergency"))
    assert n.priority is None                                         # no keyword guessing
    n, _ = rec(store, pkt(2, "check in", priority="ALERT"))
    assert (n.priority, n.priority_reason) == ("alert", "protocol:meshtastic-priority-ALERT")
    n, _ = rec(store, pkt(3, "\x07bell"))
    assert n.priority_reason == "protocol:bell" and n.preview == "bell"
    n, _ = rec(store, pkt(4, "x", priority=64))                       # DEFAULT
    assert n.priority is None
    n, _ = rec(store, pkt(5, "x", frm=0x22222222), rules=[nt.UserRule("team lead", senders=("!22222222",))])
    assert n.priority_reason == "user-rule:team lead"
    assert store.badge("mesh")["priority"] == 3


def test_m09_privacy_mode_and_desktop_notification_payload(store):
    n, _ = rec(store, pkt(1, "secret plan"), privacy=True, node_names={"!a1b2c3d4": "Alice"},
               channel_names={0: "LongFast"})
    assert n.preview is None and store.unread("mesh")["ch:0"]["last_preview"] is None
    d = nt.desktop_notification(n, privacy=True)
    assert d["summary"] == "Alice · LongFast" and d["body"] == "" and "secret" not in str(d)
    n2 = nt.from_meshtastic(pkt(2, "x" * 200, priority=110), ME)
    d2 = nt.desktop_notification(n2)
    assert len(n2.preview) == 81 and d2["hints"]["urgency"] == 2 and d2["summary"].startswith("[PRIORITY")


def test_m10_ignores_own_and_non_text_packets_and_cannot_transmit():
    assert nt.from_meshtastic(pkt(1, frm=ME), ME) is None
    assert nt.from_meshtastic(pkt(2, port="POSITION_APP"), ME) is None
    assert nt.from_meshtastic(pkt(0), ME) is None
    tree = ast.parse(Path(nt.__file__).read_text())
    mods = {a.name.split(".")[0] for x in ast.walk(tree) if isinstance(x, ast.Import) for a in x.names} | \
           {(x.module or "").split(".")[0] for x in ast.walk(tree) if isinstance(x, ast.ImportFrom)}
    assert not mods & {"serial", "meshtastic", "socket", "subprocess", "task_mesh"}
    assert not [n for n in dir(nt) if any(w in n.lower() for w in ("send", "transmit", "relay", "tx"))]


# ---- 0.3.1: per-protocol sources, MeshCore, locked/generic notifications --------------------------------
def test_031_sources_are_per_protocol_and_never_merged(store):
    a = nt.from_meshtastic(pkt(1), ME, source=nt.mesh_source("meshtastic"))
    b = nt.from_meshcore({"pubkey_prefix": "a1b2c3d4e5f6", "text": "hi", "sender_timestamp": 5}, "dm",
                         message_id="k1")
    c = nt.from_meshcore({"channel_idx": 0, "text": "Bob: hello", "sender_timestamp": 6}, "channel", message_id="k2")
    assert store.record(a) and store.record(b) and store.record(c)
    assert not store.record(b)                              # dedupe per (source, id)
    g = store.badge_group("mesh.")
    assert g["unread"] == 3 and g["by_source"]["mesh.meshtastic"]["unread"] == 1
    assert g["by_source"]["mesh.meshcore"] == {"unread": 2, "priority": 0, "conversations": 2}
    # Same conversation key on two protocols stays two conversations
    assert a.conversation == c.conversation == "ch:0"
    store.mark_read("mesh.meshcore", "ch:0")
    assert store.badge("mesh.meshtastic")["unread"] == 1
    with pytest.raises(ValueError):
        nt.mesh_source("aprs")


def test_031_meshcore_channel_sender_is_claimed_and_priority_only_from_rules():
    n = nt.from_meshcore({"channel_idx": 1, "text": "Bob: \x07help", "sender_timestamp": 1}, "channel", message_id="x")
    assert n.sender == "" and n.sender_label == "Bob (claimed)" and n.priority is None   # no bell rule on MeshCore
    r = nt.UserRule("ops", conversations=("ch:1",))
    n = nt.from_meshcore({"channel_idx": 1, "text": "Bob: x", "sender_timestamp": 1}, "channel", message_id="x",
                         rules=(r,))
    assert (n.priority, n.priority_reason) == ("alert", "user-rule:ops")
    assert nt.from_meshcore({"text": "no id"}, "dm", message_id="z") is None
    assert nt.from_meshcore({"pubkey_prefix": "ab", "text": "t"}, "dm", message_id=None) is None


def test_031_locked_notification_is_generic_and_privacy_respected():
    n = nt.from_meshtastic(pkt(9, text="secret plan", priority="ALERT"), ME, source=nt.mesh_source("meshtastic"))
    d = nt.desktop_notification(n, locked=True, protocol_label="Meshtastic")
    assert d["summary"] == "New Mesh Message [PRIORITY]" and d["body"] == ""
    assert "secret" not in str(d) and "a1b2" not in str(d) and "Meshtastic" not in str(d)
    d = nt.desktop_notification(n, privacy=True, protocol_label="Meshtastic", show_sender=False, sound=False)
    assert d["body"] == "" and d["summary"].endswith("[Meshtastic] Channel 0") and d["hints"]["suppress-sound"]
    d = nt.desktop_notification(n, protocol_label="Meshtastic")
    assert d["body"] == "secret plan" and d["hints"]["sound-name"] == "message-new-instant"
