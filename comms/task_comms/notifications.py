# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Notification-source API (Phase 4E groundwork, schema 1). See docs/NOTIFICATIONS.md.

A *source* (e.g. the future task-mesh 0.3.0 receiver, the single owner of the radio port) records
incoming items here; *consumers* (launcher tile badge, desktop notifier, a future notification centre)
only read. Rules:
* Dedupe on (source, message_id) — the protocol packet id. Recording twice is a no-op.
* origin "history-sync" (messages the node replays after connect) is stored already-read: it never
  raises a badge or a popup. Only origin "live" counts as unread.
* Reading or previewing never marks read. Only mark_read(conversation) / mark_all_read(confirm=True).
* Nothing is ever deleted here, and this module stores no message history (only notification state;
  the preview is optional and None in privacy mode).
* Priority comes ONLY from protocol metadata or an explicit user rule, and always carries its reason.
  There is no keyword guessing.
This module never transmits anything and has no radio access.
"""

import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from task_comms import paths

SCHEMA = 1
LIVE, HISTORY = "live", "history-sync"
PREVIEW_MAX = 80
# Meshtastic MeshPacket.Priority (meshtastic/protobufs mesh.proto, verified 2026-10-13): ALERT = 110,
# "Higher priority alert message used for critical alerts". BEL (0x07) is Meshtastic's documented
# alert trigger (ExternalNotificationConfig.alert_bell / CannedMessage send_bell).
# 0.3.1 correction (mesh.proto, checked 2026-10-13): MeshPacket.priority "is never sent over the air, it is only
# used internally inside of a local device node". On received packets it is local queue metadata, normally
# absent, never the sender's intent. The BEL character travels in the payload and is the real over-the-air
# alert signal. The ALERT check is kept (labelled) for packets an API client marked locally.
MESHTASTIC_ALERT = 110
BELL = "\x07"
# 0.3.1: one source per mesh protocol. Identities are never merged across protocols: a conversation key is
# always scoped by its source (e.g. "mesh.meshcore" + "dm:ab12cd34ef56").
PROTOCOL_LABELS = {"meshtastic": "Meshtastic", "meshcore": "MeshCore"}
GENERIC_SUMMARY = "New Mesh Message"


def mesh_source(protocol):
    if protocol not in PROTOCOL_LABELS:
        raise ValueError(f"unknown mesh protocol {protocol!r}")
    return f"mesh.{protocol}"

DDL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS notification(
  source TEXT NOT NULL, message_id TEXT NOT NULL, conversation TEXT NOT NULL,
  sender TEXT, sender_label TEXT, channel_label TEXT, preview TEXT,
  received_at REAL NOT NULL, origin TEXT NOT NULL, priority TEXT, priority_reason TEXT,
  read INTEGER NOT NULL DEFAULT 0, read_at REAL,
  PRIMARY KEY(source, message_id));
CREATE INDEX IF NOT EXISTS notification_conv ON notification(source, conversation, read);
"""


@dataclass
class Notification:
    source: str
    message_id: str
    conversation: str              # e.g. "ch:0" or "dm:!a1b2c3d4"
    sender: str = ""
    sender_label: str = ""
    channel_label: str = ""
    preview: str = None            # None in privacy mode
    received_at: float = field(default_factory=time.time)
    origin: str = LIVE
    priority: str = None           # None | "alert"
    priority_reason: str = None    # "protocol:meshtastic-priority-ALERT" | "protocol:bell" | "user-rule:<name>"


@dataclass
class UserRule:
    """Explicit user rule: mark messages from these senders / in these conversations as priority."""
    name: str
    senders: tuple = ()
    conversations: tuple = ()


class ConfirmationRequired(Exception):
    pass


class NotificationStore:
    def __init__(self, path: Path = None):
        self.path = Path(path or paths.data_dir("task-comms") / "notifications.sqlite")
        paths.private_dir(self.path.parent)
        os.close(os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600))
        os.chmod(self.path, 0o600)
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock, self.db:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript(DDL)
            self.db.execute("INSERT OR IGNORE INTO meta VALUES('schema', ?)", (str(SCHEMA),))

    def close(self):
        self.db.close()

    def record(self, n: Notification) -> bool:
        """-> True if new (a consumer may announce it), False for a duplicate or a history-sync item."""
        if n.origin not in (LIVE, HISTORY):
            raise ValueError("origin")
        with self.lock, self.db:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO notification(source, message_id, conversation, sender, sender_label, "
                "channel_label, preview, received_at, origin, priority, priority_reason, read, read_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (n.source, str(n.message_id), n.conversation, n.sender, n.sender_label, n.channel_label,
                 n.preview, n.received_at, n.origin, n.priority, n.priority_reason,
                 int(n.origin == HISTORY), n.received_at if n.origin == HISTORY else None))
        return cur.rowcount == 1 and n.origin == LIVE

    def unread(self, source):
        """Per conversation: {conversation: {"count", "priority", "last_sender", "last_preview"}}.
        Read-only: never marks anything read."""
        out = {}
        with self.lock:
            rows = self.db.execute("SELECT * FROM notification WHERE source=? AND read=0 ORDER BY received_at",
                                   (source,)).fetchall()
        for r in rows:
            c = out.setdefault(r["conversation"], {"count": 0, "priority": 0, "last_sender": "",
                                                   "last_preview": None})
            c["count"] += 1
            c["priority"] += int(r["priority"] is not None)
            c["last_sender"] = r["sender_label"] or r["sender"]
            c["last_preview"] = r["preview"]
        return out

    def badge(self, source):
        u = self.unread(source)
        return {"unread": sum(c["count"] for c in u.values()), "priority": sum(c["priority"] for c in u.values()),
                "conversations": len(u)}

    def badge_group(self, prefix="mesh."):
        """Combined badge over every source starting with prefix, plus the per-source breakdown. Read-only."""
        with self.lock:
            rows = self.db.execute(
                "SELECT source, COUNT(*), SUM(priority IS NOT NULL), COUNT(DISTINCT conversation) FROM notification "
                "WHERE read=0 AND substr(source, 1, ?)=? GROUP BY source", (len(prefix), prefix)).fetchall()
        by = {r[0]: {"unread": r[1], "priority": int(r[2] or 0), "conversations": r[3]} for r in rows}
        return {"unread": sum(v["unread"] for v in by.values()), "priority": sum(v["priority"] for v in by.values()),
                "by_source": by}

    def mark_read(self, source, conversation):
        with self.lock, self.db:
            return self.db.execute("UPDATE notification SET read=1, read_at=? WHERE source=? AND conversation=? "
                                   "AND read=0", (time.time(), source, conversation)).rowcount

    def mark_all_read(self, source, confirm=False):
        if not confirm:
            raise ConfirmationRequired("mark all as read needs explicit confirmation")
        with self.lock, self.db:
            return self.db.execute("UPDATE notification SET read=1, read_at=? WHERE source=? AND read=0",
                                   (time.time(), source)).rowcount

    def count_all(self, source):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM notification WHERE source=?", (source,)).fetchone()[0]


def classify_priority(text, packet_priority, sender, conversation, rules=()):
    """-> (priority, reason) from protocol metadata or user rules only."""
    if packet_priority in (MESHTASTIC_ALERT, "ALERT"):
        return "alert", "protocol:meshtastic-priority-ALERT"
    if text and BELL in text:
        return "alert", "protocol:bell"
    for r in rules:
        if sender in r.senders or conversation in r.conversations:
            return "alert", f"user-rule:{r.name}"
    return None, None


def from_meshtastic(packet, my_node_num, origin=LIVE, privacy=False, channel_names=None, node_names=None,
                    rules=(), source="mesh"):
    """Decoded Meshtastic packet dict (as the meshtastic Python API delivers it) -> Notification | None.

    Only TEXT_MESSAGE_APP from other nodes; our own packets and other port numbers are ignored."""
    dec = packet.get("decoded") or {}
    if dec.get("portnum") != "TEXT_MESSAGE_APP":
        return None
    src = packet.get("from")
    if src is None or src == my_node_num or packet.get("id") in (None, 0):
        return None
    text = dec.get("text")
    if text is None:
        payload = dec.get("payload", b"")
        text = payload.decode("utf-8", "replace") if isinstance(payload, (bytes, bytearray)) else ""
    sender = f"!{int(src):08x}"
    to = packet.get("to")
    ch = int(packet.get("channel", 0) or 0)
    conversation = f"dm:{sender}" if to == my_node_num else f"ch:{ch}"
    prio, reason = classify_priority(text, packet.get("priority"), sender, conversation, rules)
    clean = text.replace(BELL, "").strip()
    preview = None if privacy else (clean[:PREVIEW_MAX] + ("…" if len(clean) > PREVIEW_MAX else ""))
    return Notification(source=source, message_id=str(packet["id"]), conversation=conversation, sender=sender,
                        sender_label=(node_names or {}).get(sender, sender),
                        channel_label="Direct message" if conversation.startswith("dm:")
                        else (channel_names or {}).get(ch, f"Channel {ch}"),
                        preview=preview, received_at=float(packet.get("rxTime") or time.time()), origin=origin,
                        priority=prio, priority_reason=reason)


def from_meshcore(payload, kind, origin=LIVE, privacy=False, contact_names=None, channel_names=None, rules=(),
                  message_id=None, received_at=None):
    """meshcore_py CONTACT_MSG_RECV / CHANNEL_MSG_RECV payload -> Notification | None (0.3.1).

    kind: "dm" | "channel". MeshCore has no packet id on receive, so message_id is the caller's dedupe key
    (protocol adapter: sha256 over sender/channel, sender_timestamp and text). MeshCore carries no priority
    field: priority comes only from user rules. Channel messages have no authenticated sender; the
    "Name: text" prefix is shown as a claimed name, never mapped to a contact."""
    if not isinstance(payload, dict) or not isinstance(payload.get("text"), str) or not message_id:
        return None
    text = payload["text"].replace("\x00", "")
    if kind == "dm":
        prefix = str(payload.get("pubkey_prefix") or "")
        if not prefix:
            return None
        conversation, sender = f"dm:{prefix}", prefix
        label = (contact_names or {}).get(prefix, prefix)
        channel_label = "Direct message"
    elif kind == "channel":
        idx = payload.get("channel_idx")
        if not isinstance(idx, int):
            return None
        conversation = f"ch:{idx}"
        name, sep, rest = text.partition(": ")
        claimed = name.strip()[:32] if sep and 0 < len(name.strip()) <= 32 else ""
        sender, label = "", (f"{claimed} (claimed)" if claimed else "unknown sender")
        text = rest if claimed else text
        channel_label = (channel_names or {}).get(idx, f"Channel {idx}")
    else:
        raise ValueError("kind")
    prio, reason = None, None
    for r in rules:
        if (sender and sender in r.senders) or conversation in r.conversations:
            prio, reason = "alert", f"user-rule:{r.name}"
            break
    clean = text.strip()
    preview = None if privacy else (clean[:PREVIEW_MAX] + ("…" if len(clean) > PREVIEW_MAX else ""))
    return Notification(source=mesh_source("meshcore"), message_id=str(message_id), conversation=conversation,
                        sender=sender, sender_label=label, channel_label=channel_label, preview=preview,
                        received_at=float(received_at or time.time()), origin=origin, priority=prio,
                        priority_reason=reason)


def desktop_notification(n: Notification, privacy=False, locked=False, protocol_label=None, sound=True,
                         show_sender=True):
    """Arguments for org.freedesktop.Notifications.Notify (Desktop Notifications Spec 1.2), no shell.
    -> dict(app_name, summary, body, hints). Consumers send it via QtDBus; urgency 1 (normal) unless priority.

    locked=True (signed out or auth state uncertain): generic "New Mesh Message" with no sender, channel,
    protocol detail or preview; the priority marker is kept (it reveals no content). privacy=True: no preview.
    show_sender=False: no sender name."""
    hints = {"urgency": 2 if n.priority else 1, "category": "im.received", "desktop-entry": "task-mesh"}
    if sound:
        hints["sound-name"] = "message-new-instant"
    else:
        hints["suppress-sound"] = True
    if locked:
        summary = GENERIC_SUMMARY + (" [PRIORITY]" if n.priority else "")
        return {"app_name": "T.A.S.K. Mesh", "summary": summary, "body": "", "hints": hints}
    who = (n.sender_label or n.sender) if show_sender else ""
    summary = " · ".join(x for x in (who, n.channel_label) if x)
    if protocol_label:
        summary = f"[{protocol_label}] " + summary
    body = "" if privacy or n.preview is None else n.preview
    if n.priority:
        summary = f"[PRIORITY — {n.priority_reason}] " + summary
    return {"app_name": "T.A.S.K. Mesh", "summary": summary, "body": body, "hints": hints}
