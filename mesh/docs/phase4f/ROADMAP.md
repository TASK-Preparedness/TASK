<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# Roadmap after Phase 4F (existing numbering kept)

| Phase | Scope | Precondition |
|---|---|---|
| **4F** (this) | Comms hub: task-mesh 0.3.0 (Meshtastic + MeshCore, optional user service, notifications), comms 0.3.1, launcher 0.3.3 badge | Pi hardware test of HARDWARE-CHECKLIST.md |
| **4G** | Inventory (task-inventory 0.1.0), SPEC-INVENTORY.md | 4F hardware-tested |
| 4H | Medical via supported Resources category view, SPEC-MEDICAL.md (reference only; patient records remain out of scope until a separate auth/encryption/audit design) | resources category entry point |
| 4I | Maps online/offline polish, SPEC-MAPS.md | |
| 4J | APRS (task-aprs 0.2), SPEC-APRS.md | TNC/radio test |
| 4K | Devices tile → native device view on Core devices API, SPEC-DEVICES.md | |
| 4L | App Manager refinements (install state, signed manifests) | |
| 4M | Auth hardening: at-rest encryption for messages/inventory, per-module audit, idle lock across apps | Core feature approval |
| 4N | Mission Planner (currently placeholder manifest) | 4I, 4K |
| 4O | Sewing resources: FreeSewing offline. **Licensing:** FreeSewing code is MIT; pattern designs/docs carry their own licences (check per design, typically MIT for code, CC for docs) — ship only content whose licence is recorded; never embed freesewing.org | licence inventory |
