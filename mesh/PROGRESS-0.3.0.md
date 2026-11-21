# task-mesh 0.3.0 progress (branch phase4f-mesh)
- [x] 12:19 Branch phase4f-mesh from a17e85f (0.2.0). Baseline: 313 tests pass (/tmp/meshtest.sh).
- [x] meshcore research: MIT, 2.3.15, Debian Cryptodome incompatibility (docs/phase4f/MESHCORE-RESEARCH.md)
- [x] hub core: model, store (0600), priority, dedupe, unread (task_mesh/hub)
- [x] notifications manager (jeepney D-Bus) + comms 0.3.1 API (phase4f 3412f31)
- [x] device manager (explicit assignments only) + flock device locks + read-only probe
- [x] adapters: Meshtastic (wrap provider), MeshCore (real lib)
- [x] task-mesh-service + IPC + systemd --user unit (disabled)
- [x] GUI tabs + service/direct mode
- [x] launcher badge (launcher 0.3.3)
- [x] tests: mesh 344, comms 29, launcher 300 (+5), core 178
- [x] packaging, docs, release zip: /workspace/TASK-Phase4F-Mesh-0.3.0.zip (sha256 d3833f0f…e86a8d, SHA256SUMS verified 2026-10-13 14:09)
- [x] MeshCore adapter on real meshcore_py + frame-level SimCompanion (smoke OK)

## Status 2026-10-13 13:47 (master directive A–F) — release assembled
- [x] A AUDIT-4F.md · [x] B DEPENDENCIES-4F.md · [x] C ROADMAP.md · [x] F SPEC-INVENTORY/MEDICAL/MAPS/APRS/DEVICES
- [x] D hub, adapters, service, GUI tabs, notifications (quiet/mute/history), launcher 0.3.3 badge
- [x] tests: mesh 344 (313 baseline + 31 new), comms 29, launcher 300 (+5), core 178
- [x] E builder, preflight, installer, rollback, README, deps-arm64; zip at TASK-Phase4F-Mesh-0.3.0.zip (also agent attachment 13:48)
- [ ] Inventory code: deferred (4F not hardware-tested); spec only
- [ ] Pi install / hardware acceptance: user decision only; service stays disabled; do not enable without Jo
