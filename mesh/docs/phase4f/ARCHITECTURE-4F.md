<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# Architecture (task-mesh 0.3.0)

```
 /dev/serial/by-id/* ──(assigned only)──> DeviceManager ──factories──> MeshtasticAdapter | MeshCoreAdapter
                         per-port flock                                   (thread, backoff, read-only session)
                                                    │ HubMessage / HubNode / DeviceStatus
                                                    v
                                     Hub (engine.py): rules → HubStore (hub.sqlite3 0600)
                                                    │            └─ unread = live ∧ inbound ∧ !read
                                                    ├─> NotificationManager → comms NotificationStore (badge source)
                                                    │                      → jeepney Notify (session bus)
                                                    └─> api() ── IpcServer (mesh.sock 0600, same uid)   [service mode]
 GUI (Qt): HubTabs [All Messages | Meshtastic | MeshCore | Devices | Network Status]
   direct mode : in-process Hub (MeshCore adapters) + 0.2.0 RadioWorker for Meshtastic (locked, feeds hub)
   service mode: HubClient over the socket; RadioWorker never autoconnects
 Launcher 0.3.3 tile: meshbadge → socket "unread" (pure query) else comms store opened mode=ro
```
* Common adapter interface: `start() / stop() / send_text(conversation, text) / protocol / key`, events into a sink
  (`on_message, on_node, on_adapter_status`).
* Message schema (hub.sqlite3 `message`): id, protocol, device, key (dedupe, unique per protocol), direction, kind,
  conversation (recipient: `dm:<native id>` or channel `ch:<n>`), sender, sender_label, text, ts, sender_ts, origin
  (live|sync), priority, priority_source, snr, rssi, hops, state (rx/delivery: received|queued|sent|delivered|failed|no-ack),
  read, read_at.
* Mark-read rules: only when the user selects a conversation while signed in; never by the badge, notifications, sync,
  IPC reads or the launcher. Own outgoing messages are stored read.
* Priority: `protocol:meshtastic-bell` (BEL) or `user-rule:<name>` from notifications.json; never from text heuristics.
* Bridge: `task_mesh.hub.bridge.Bridge` is an extension interface only; `forward()` raises BridgeDisabled. No relay.
