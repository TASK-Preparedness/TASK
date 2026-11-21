<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# Notification-source API (task_comms.notifications, schema 1) — Phase 4E groundwork

Status: source code + tests on branch phase4e. **Not packaged in 4E** (python3-task-comms on the Pi stays 0.3.0).
It ships with its first consumer, the task-mesh 0.3.0 follow-up (docs/phase4e/MESH-NOTIFICATIONS-PLAN.md).

## Model
| field | meaning |
|---|---|
| source | module id, e.g. `mesh` |
| message_id | protocol packet id; dedupe key together with source |
| conversation | `ch:<index>` or `dm:!<node id hex>` |
| sender / sender_label / channel_label | ids and display labels |
| preview | ≤ 80 chars, `None` in privacy mode |
| origin | `live` or `history-sync` (replayed on connect: stored read, never announced) |
| priority / priority_reason | `alert` + `protocol:meshtastic-priority-ALERT` (MeshPacket.priority = 110), `protocol:bell` (BEL 0x07, Meshtastic's alert_bell trigger) or `user-rule:<name>`. Never keywords. |

Store: `~/.local/share/task-comms/notifications.sqlite` (0600, WAL). API: `record(n) -> bool new`,
`unread(source)` / `badge(source)` (read-only, never marks read), `mark_read(source, conversation)`,
`mark_all_read(source, confirm=True)` (raises without confirm). No delete API; message history is not stored here.

`from_meshtastic(packet_dict, my_node_num, origin, privacy, channel_names, node_names, rules)` maps a decoded
Meshtastic packet (TEXT_MESSAGE_APP only, own packets ignored) to a Notification.
`desktop_notification(n, privacy)` returns the arguments for `org.freedesktop.Notifications.Notify`
(urgency 2 only for labelled priority). Sending it (QtDBus, no shell) is the consumer's job.

The module has no radio, serial, socket or subprocess access and no send/transmit function (tested).

## 0.3.1 (task-mesh 0.3.0)
- **One source per protocol:** `mesh_source("meshtastic")` gives `mesh.meshtastic`, and `mesh_source("meshcore")` gives `mesh.meshcore`. Conversation keys are only meaningful together with their source, so identities are never merged across protocols.
- **`badge_group("mesh.")`:** read-only. Returns the combined unread and priority counts plus `by_source`, which the launcher Mesh tile uses.
- **`from_meshcore(payload, "dm"|"channel", message_id=…)`:**
  - The caller supplies the dedupe key, because MeshCore has no receive packet id.
  - A channel message's "Name: " prefix is shown as a *claimed* name and is never mapped to a contact.
  - Priority comes from user rules only, because MeshCore has no priority metadata.
- **`desktop_notification(..., locked=True)`:** the summary is the generic "New Mesh Message" (plus "[PRIORITY]" if flagged). There is no sender, channel, protocol or preview. Use it whenever the sign-in state is locked or uncertain.
- **Other `desktop_notification` options:**
  - `protocol_label`, which adds e.g. "[MeshCore]" to the summary;
  - `show_sender`;
  - `sound`, which sets the `sound-name` or `suppress-sound` hint.
- **Correction for Meshtastic `MeshPacket.priority`.** mesh.proto says the field is never sent over the air. For received packets, the BEL character (`protocol:bell`) is therefore the only sender-side alert signal. `protocol:meshtastic-priority-ALERT` can only appear when something local set the field.
