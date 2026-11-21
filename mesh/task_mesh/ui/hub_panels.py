# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""0.3.0 tabs: All Messages | Meshtastic | MeshCore | Devices | Network Status.

The GUI talks to the hub through HubAccess: IPC to task-mesh-service when it runs, else an in-process hub
(direct mode). Message content is shown only while signed in to task-core; counts are always shown. Viewing a
conversation (signed in) marks only that conversation read; opening the app clears nothing. Sending is an
explicit click, needs an operator session (verified by the hub) and never happens otherwise."""

from __future__ import annotations

import datetime
import logging
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from task_mesh.hub.model import LABELS

log = logging.getLogger(__name__)


class HubAccess:
    def __init__(self, local_hub=None, client=None) -> None:
        self.local, self.client = local_hub, client

    @property
    def mode(self) -> str:
        return "service" if self.client is not None else "direct"

    def call(self, method: str, **params):
        if self.client is not None:
            return self.client.call(method, **params)
        return self.local.api(method, params)


def _ts(t) -> str:
    try:
        return datetime.datetime.fromtimestamp(float(t)).strftime("%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return "—"


def conv_label(c: dict, names: Optional[dict] = None) -> str:
    who = c["conversation"]
    if who.startswith("dm:"):
        who = "DM " + (names or {}).get(who[3:], who[3:])
    else:
        who = "Channel " + who[3:]
    extra = []
    if c.get("unread"):
        extra.append(f"{c['unread']} unread")
    if c.get("priority"):
        extra.append(f"{c['priority']} PRIORITY")
    return f"[{LABELS.get(c['protocol'], c['protocol'])}] {who}" + (f"  ({', '.join(extra)})" if extra else "")


class ConversationPanel(QWidget):
    def __init__(self, access: HubAccess, gate, protocol: Optional[str] = None, parent=None) -> None:
        super().__init__(parent)
        self.access, self.gate, self.protocol = access, gate, protocol
        self.current: Optional[tuple] = None
        lay = QVBoxLayout(self)
        split = QSplitter()
        self.convs = QListWidget()
        self.convs.setObjectName(f"conversations-{protocol or 'all'}")
        self.convs.currentItemChanged.connect(lambda *_: self.open_selected())
        split.addWidget(self.convs)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.lock_note = QLabel("Sign in (Meshtastic tab › Messages › Sign in) to view message content. "
                                "Counts are shown; nothing is marked read while locked.")
        self.lock_note.setWordWrap(True)
        rl.addWidget(self.lock_note)
        self.msgs = QListWidget()
        self.msgs.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        rl.addWidget(self.msgs, 1)
        row = QHBoxLayout()
        self.compose = QLineEdit()
        self.compose.setPlaceholderText("Message (sent only when you press Send)")
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self.send)
        row.addWidget(self.compose, 1)
        row.addWidget(self.send_btn)
        self.mute_btn = QPushButton("Mute conversation")
        self.mute_btn.setCheckable(True)
        self.mute_btn.toggled.connect(self.toggle_mute)
        row.addWidget(self.mute_btn)
        if protocol is None:
            self.compose.hide()
            self.send_btn.hide()
            rl.addWidget(QLabel("Reply from the protocol's own tab. Identities are never merged across protocols."))
        rl.addLayout(row)
        self.status = QLabel("")
        rl.addWidget(self.status)
        split.addWidget(right)
        split.setSizes([300, 600])
        lay.addWidget(split)

    def refresh(self) -> None:
        try:
            convs = self.access.call("conversations", protocol=self.protocol)
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"Hub unavailable: {type(exc).__name__}")
            return
        unlocked = bool(self.gate is not None and self.gate.unlocked)
        self.lock_note.setVisible(not unlocked)
        sel = self.current
        self.convs.blockSignals(True)
        self.convs.clear()
        for c in convs:
            it = QListWidgetItem(conv_label(c))
            it.setData(Qt.ItemDataRole.UserRole, (c["protocol"], c["conversation"]))
            self.convs.addItem(it)
            if sel == (c["protocol"], c["conversation"]):
                self.convs.setCurrentItem(it)
        self.convs.blockSignals(False)
        self.send_btn.setEnabled(unlocked and self.current is not None and self.protocol is not None)
        if sel and unlocked:
            self._load(*sel, mark=False)
        elif not unlocked:
            self.msgs.clear()

    def toggle_mute(self, on: bool) -> None:
        """Per-conversation notification mute (protocol-scoped key; counts are unaffected)."""
        if self.current is None:
            return
        key = f"{self.current[0]}|{self.current[1]}"
        try:
            cur = set(self.access.call("status")["notifications"].get("muted_conversations") or ())
            cur = (cur | {key}) if on else (cur - {key})
            self.access.call("set_notify", settings={"muted_conversations": sorted(cur)})
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"Could not change mute: {exc}")

    def open_selected(self) -> None:
        it = self.convs.currentItem()
        if it is None:
            return
        self.current = it.data(Qt.ItemDataRole.UserRole)
        try:
            muted = set(self.access.call("status")["notifications"].get("muted_conversations") or ())
        except Exception:  # noqa: BLE001
            muted = set()
        self.mute_btn.blockSignals(True)
        self.mute_btn.setChecked(f"{self.current[0]}|{self.current[1]}" in muted)
        self.mute_btn.blockSignals(False)
        if self.gate is not None and self.gate.unlocked:
            self._load(*self.current, mark=True)
        self.send_btn.setEnabled(bool(self.gate and self.gate.unlocked) and self.protocol is not None)

    def _load(self, protocol: str, conversation: str, mark: bool) -> None:
        rows = self.access.call("messages", protocol=protocol, conversation=conversation, limit=300)
        self.msgs.clear()
        for r in rows:
            who = "me" if r["direction"] == "out" else (r["sender_label"] or r["sender"] or "unknown")
            flags = []
            if r.get("priority"):
                flags.append(f"PRIORITY ({r.get('priority_source')})")
            if r.get("origin") == "sync":
                flags.append("received while away")
            if r["direction"] == "out":
                flags.append(r.get("state", ""))
            sig = f" SNR {r['snr']:.1f}" if isinstance(r.get("snr"), (int, float)) else ""
            line = f"{_ts(r['ts'])}  [{LABELS[r['protocol']]}] {who}: {r['text']}" + (
                f"   [{'; '.join(f for f in flags if f)}]" if flags else "") + sig
            self.msgs.addItem(line)
        self.msgs.scrollToBottom()
        if mark:
            self.access.call("mark_read", protocol=protocol, conversation=conversation)

    def send(self) -> None:
        if self.current is None or self.protocol is None:
            return
        ok, why = self.gate.require("operator")
        if not ok:
            self.status.setText(why)
            return
        text = self.compose.text()
        try:
            self.access.call("send", protocol=self.protocol, conversation=self.current[1], text=text,
                             explicit_user_action=True, session=self.gate.client.token)
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"Not sent: {exc}")
            return
        self.compose.clear()
        self.status.setText("Handed to the radio.")
        self._load(*self.current, mark=False)


class NodesPanel(QWidget):
    COLS = ("Name", "Id", "Role", "Last heard", "SNR", "Hops")

    def __init__(self, access: HubAccess, protocol: str, parent=None) -> None:
        super().__init__(parent)
        self.access, self.protocol = access, protocol
        lay = QVBoxLayout(self)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        lay.addWidget(self.table)

    def refresh(self) -> None:
        try:
            rows = self.access.call("nodes", protocol=self.protocol)
        except Exception:  # noqa: BLE001
            return
        self.table.setRowCount(len(rows))
        for i, n in enumerate(rows):
            vals = (n.get("name") or "—", (n.get("key") or "")[:16], n.get("role") or "—", _ts(n.get("last_heard")),
                    "—" if n.get("snr") is None else f"{n['snr']:.1f}", "—" if n.get("hops") is None else str(n["hops"]))
            for j, v in enumerate(vals):
                self.table.setItem(i, j, QTableWidgetItem(v))


class DevicesPanel(QWidget):
    COLS = ("Device (by-id)", "Protocol", "State", "Owner", "Model", "Firmware", "Battery", "Detail")

    def __init__(self, access: HubAccess, parent=None) -> None:
        super().__init__(parent)
        self.access = access
        lay = QVBoxLayout(self)
        note = QLabel("Only devices you assign here are opened. Unassigned ports (GPS, TNC, SDR, …) are never "
                      "touched. Identify sends one read-only query; nothing is configured or flashed.")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.buttons = {}
        for label, proto in (("Use as Meshtastic", "meshtastic"), ("Use as MeshCore", "meshcore"),
                             ("Ignore", "ignore"), ("Clear", None)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, p=proto: self.assign(p))
            row.addWidget(b)
            self.buttons[label] = b
        ident = QPushButton("Identify (read-only)")
        ident.clicked.connect(self.identify)
        row.addWidget(ident)
        lay.addLayout(row)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        self.keys: list[str] = []

    def selected_key(self) -> Optional[str]:
        r = self.table.currentRow()
        return self.keys[r] if 0 <= r < len(self.keys) else None

    def refresh(self) -> None:
        try:
            st = self.access.call("status")
        except Exception as exc:  # noqa: BLE001
            self.msg.setText(f"Hub unavailable: {type(exc).__name__}")
            return
        devs = sorted(st.get("devices") or [], key=lambda d: d["key"])
        cur = self.selected_key()
        self.keys = [d["key"] for d in devs]
        self.table.setRowCount(len(devs))
        for i, d in enumerate(devs):
            vals = (d["key"], LABELS.get(d.get("protocol"), "unassigned"), d.get("state", ""), d.get("owner", ""),
                    d.get("model", ""), d.get("firmware", ""), "—" if d.get("battery") is None else f"{d['battery']} %",
                    d.get("detail", ""))
            for j, v in enumerate(vals):
                self.table.setItem(i, j, QTableWidgetItem(str(v)))
        if cur in self.keys:
            self.table.selectRow(self.keys.index(cur))

    def assign(self, proto: Optional[str]) -> None:
        key = self.selected_key()
        if key is None:
            self.msg.setText("Select a device first.")
            return
        try:
            self.access.call("set_assignment", key=key, protocol=proto, explicit_user_action=True)
            self.msg.setText(f"{key}: {LABELS.get(proto, proto or 'cleared')}")
        except Exception as exc:  # noqa: BLE001
            self.msg.setText(f"Not changed: {exc}")
        self.refresh()

    def identify(self) -> None:
        key = self.selected_key()
        if key is None:
            self.msg.setText("Select a device first.")
            return
        try:
            r = self.access.call("identify", key=key, explicit_user_action=True)
            self.msg.setText(f"{key}: {LABELS.get(r.get('protocol'), 'not identified')} ({r.get('how')}). "
                             "Assign it with the buttons above. UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.")
        except Exception as exc:  # noqa: BLE001
            self.msg.setText(f"Identify failed: {exc}")


class StatusPanel(QWidget):
    def __init__(self, access: HubAccess, service_toggle: Optional[Callable[[bool], str]] = None,
                 daemon_info: Optional[Callable[[], object]] = None, parent=None) -> None:
        super().__init__(parent)
        self.access = access
        self.service_toggle = service_toggle
        lay = QVBoxLayout(self)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.summary)
        box = QGroupBox("Desktop notifications")
        bl = QVBoxLayout(box)
        self.checks = {}
        for key, label in (("enabled", "Show desktop notifications"),
                           ("show_preview", "Show message preview (only while signed in)"),
                           ("quiet", "Quiet mode (no pop-ups or sound; counts still update)"),
                           ("show_sender", "Show sender name"), ("sound", "Play sound"),
                           ("mute_meshtastic", "Mute Meshtastic"), ("mute_meshcore", "Mute MeshCore")):
            c = QCheckBox(label)
            c.toggled.connect(lambda _v, k=key: self.save_settings())
            bl.addWidget(c)
            self.checks[key] = c
        info = daemon_info() if daemon_info else None
        self.daemon = QLabel("Notification daemon: " + (" ".join(str(x) for x in info[:3]) if info else
                             "none found on the session bus (popups off; the launcher badge still works)"))
        self.daemon.setWordWrap(True)
        bl.addWidget(self.daemon)
        lay.addWidget(box)
        row = QHBoxLayout()
        self.svc_on = QPushButton("Start background service (this login only)")
        self.svc_off = QPushButton("Stop background service")
        self.svc_on.clicked.connect(lambda: self._toggle(True))
        self.svc_off.clicked.connect(lambda: self._toggle(False))
        row.addWidget(self.svc_on)
        row.addWidget(self.svc_off)
        lay.addLayout(row)
        lay.addStretch(1)
        self._loading = False

    def _toggle(self, on: bool) -> None:
        if self.service_toggle is None:
            return
        verb = "start" if on else "stop"
        if QMessageBox.question(self, "Background service",
                                f"{verb.capitalize()} task-mesh-service now?\n\nIt is not enabled at login. The radios are handed "
                                "over between this window and the service; nothing is transmitted.") \
                != QMessageBox.StandardButton.Yes:
            return
        self.summary.setText(self.service_toggle(on))

    def refresh(self) -> None:
        try:
            st = self.access.call("status")
        except Exception as exc:  # noqa: BLE001
            self.summary.setText(f"Hub unavailable: {type(exc).__name__}")
            return
        u = st["unread"]
        lines = [f"Mode: {'background service (task-mesh-service ' + st['version'] + ', pid ' + str(st.get('pid', '?')) + ')' if self.access.mode == 'service' else 'direct (this window owns the radios)'}",
                 f"Sign-in state seen by notifications: {st['auth']}",
                 f"Unread: {u['total']} (priority {u['priority']}) — " + ", ".join(
                     f"{LABELS[p]} {v['unread']}" + (f" / {v['priority']} priority" if v['priority'] else "")
                     for p, v in u["by_protocol"].items())]
        for d in st.get("devices") or []:
            lines.append(f"• {d['key']}: {LABELS.get(d.get('protocol'), 'unassigned')} — {d.get('state')}"
                         + (f" ({d['detail']})" if d.get("detail") else ""))
        self.summary.setText("\n".join(lines))
        s = st.get("notifications") or {}
        self._loading = True
        for k in ("enabled", "show_preview", "show_sender", "sound", "quiet"):
            self.checks[k].setChecked(bool(s.get(k)))
        muted = set(s.get("muted_protocols") or ())
        self.checks["mute_meshtastic"].setChecked("meshtastic" in muted)
        self.checks["mute_meshcore"].setChecked("meshcore" in muted)
        self._loading = False

    def save_settings(self) -> None:
        if self._loading:
            return
        muted = [p for p in ("meshtastic", "meshcore") if self.checks[f"mute_{p}"].isChecked()]
        s = {k: self.checks[k].isChecked() for k in ("enabled", "show_preview", "show_sender", "sound", "quiet")}
        s["muted_protocols"] = muted
        try:
            self.access.call("set_notify", settings=s)
        except Exception:  # noqa: BLE001
            pass


class HubTabs:
    """Builds the 0.3.0 tab set into an existing QTabWidget and refreshes it on a timer."""

    def __init__(self, tabs: QTabWidget, access: HubAccess, gate, meshtastic_widgets: list,
                 service_toggle=None, daemon_info=None, interval_ms: int = 2000) -> None:
        self.access, self.gate = access, gate
        self.all = ConversationPanel(access, gate, None)
        self.mt_msgs = ConversationPanel(access, gate, "meshtastic")
        self.mc_msgs = ConversationPanel(access, gate, "meshcore")
        self.mc_nodes = NodesPanel(access, "meshcore")
        self.devices = DevicesPanel(access)
        self.status = StatusPanel(access, service_toggle, daemon_info)
        self.mt_nodes = NodesPanel(access, "meshtastic")
        mt = QTabWidget()
        mt.addTab(self.mt_msgs, "Messages (all devices)")
        for w, label in meshtastic_widgets:
            mt.addTab(w, label)
        mt.addTab(self.mt_nodes, "Nodes (background service)" if meshtastic_widgets else "Nodes")
        self.mt_tabs, self.mc_tabs = mt, None
        mc = QTabWidget()
        mc.addTab(self.mc_msgs, "Messages")
        mc.addTab(self.mc_nodes, "Contacts, nodes & repeaters")
        self.mc_tabs = mc
        while tabs.count():
            tabs.removeTab(0)
        tabs.addTab(self.all, "All Messages")
        tabs.addTab(mt, "Meshtastic")
        tabs.addTab(mc, "MeshCore")
        tabs.addTab(self.devices, "Devices")
        tabs.addTab(self.status, "Network Status")
        self.tabs = tabs
        self._auth_seen = None
        self._ticks = 0
        self.timer = QTimer(tabs)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(interval_ms)

    def reset_auth(self) -> None:
        self._auth_seen = None             # service (re)connected: report sign-in state again

    def select(self, protocol: str, conversation: str) -> bool:
        """Show one conversation (notification click). Selecting follows the normal mark-read rule."""
        panel, outer, inner = {"meshtastic": (self.mt_msgs, 1, self.mt_tabs),
                               "meshcore": (self.mc_msgs, 2, self.mc_tabs)}.get(protocol, (None, None, None))
        if panel is None:
            return False
        self.tabs.setCurrentIndex(outer)
        inner.setCurrentIndex(0)
        panel.refresh()
        for i in range(panel.convs.count()):
            if tuple(panel.convs.item(i).data(Qt.ItemDataRole.UserRole) or ()) == (protocol, conversation):
                panel.convs.setCurrentRow(i)
                return True
        return False

    def refresh(self) -> None:
        unlocked = bool(self.gate is not None and self.gate.unlocked)
        self._ticks += 1
        if unlocked != self._auth_seen or (unlocked and self._ticks % 30 == 0):   # service may have restarted
            try:
                self.access.call("auth", session=self.gate.client.token if unlocked else None)
                self._auth_seen = unlocked
            except Exception:  # noqa: BLE001
                pass
        for p in (self.all, self.mt_msgs, self.mc_msgs, self.mc_nodes, self.devices, self.status, self.mt_nodes):
            if p is None:
                continue
            try:
                p.refresh()
                self._fail = None
            except Exception as exc:  # noqa: BLE001
                if getattr(self, "_fail", None) != type(exc).__name__:   # log once per failure kind, not every tick
                    self._fail = type(exc).__name__
                    log.warning("tab refresh failed (%s)", self._fail, extra={"event": "mesh.refresh_failed"})
