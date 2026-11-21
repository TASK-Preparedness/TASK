<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# Security review — task-mesh 0.3.1
| Area | Assessment |
|---|---|
| IPC exposure | AF_UNIX in $XDG_RUNTIME_DIR/task (0700) socket 0600, SO_PEERCRED uid == service uid, JSON only, 256 KiB line cap. No network. |
| Client-supplied ids | `_`-prefixed params stripped; connection id stamped server-side (A01). Focus TTL clamped to 30 s. |
| Content over IPC | message bodies readable by the same uid without a Core session — equal to reading the 0600 DB; UI shows content only when signed in. Events on the stream carry ids/counts, not text (A02). |
| Transmit | only `send` with explicit_user_action True AND Core role operator/administrator verified by the service (session.whoami); byte limits; per-protocol adapter (A04). No relay. |
| Serial ownership | service-client mode never opens ports; flock per port; GPS ttyACM0 never assigned/opened unless the user assigns it (not done by us). |
| Notification click | only internal integer row id from our own map; unknown ids/actions ignored; GUI launched with argv list, no shell, needs DISPLAY (A14, A15). |
| Notification content | generic when signed out/unknown; preview off by default; no message text in logs (A19). |
| Opt-in setup tool | writes two user files only on --enable; never a second provider when a system one exists; --disable removes only marked files; no root, no daemon install (A18). |
| systemd | unit unchanged (ProtectSystem=strict, NoNewPrivileges, AF_UNIX only); still shipped disabled; GUI buttons start/stop only, never enable. |
| Residual risks | same-uid malware can read history (as before); notification daemon sees whatever we send when unlocked+preview on; `dbus-update-activation-environment --systemd` exports DISPLAY/XAUTHORITY to all user units (standard desktop behaviour, opt-in). |
