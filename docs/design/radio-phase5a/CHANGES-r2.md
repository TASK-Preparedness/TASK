> HISTORICAL / SUPERSEDED for integration and safety decisions by SOURCE-RECONCILIATION-r3.1.md, ARCHITECTURE.md and ADAPTER-API-SPEC.md. Retained for history only; no commands or capabilities here authorize action.

<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Phase 5A Milestone A: changes in r2 (2026-10-30)

Trigger: the user approved a requirement change. **Milestone B includes APRS receive AND transmit**, built into the architecture, implementation and tests from the start. Docs only: no code, no Pi touched, nothing transmitted.

- ARCHITECTURE: link/, kiss/, tx/ components; the simulator is a separate package `task_radio_sim`; a unified LinkManager (single owner, TX queue, backpressure, no replay on reconnect); 5-way ownership detection; listen-only transport probe with verified/assumed recording; Packet vs ReceptionMeta; Transmit panel (typed-callsign enable, KILL); TX enablement **not persisted**; TxGuard; TX status lifecycle; APRS messaging (msg IDs, ack/rej, retries 0/30/60/120/240 s, 5 max); a list of PENDING existing-API assumptions.
- ADAPTER-API-SPEC: rewritten as r2. Full TX API (`send_frame`, `send_message`, `write_frame` with a single-use GuardTicket, `TxPolicyHook`, `TxStatusChanged`, `TxEnablementChanged`, `TransportVerdict`, `Ownership`); structural test-safety rules.
- PROTOCOL-RESEARCH: new §9a with the KISS/AX.25/APRS101 standards used for TX, and UV-PRO TX unknowns. Vendor TX stays out of scope (capability absent).
- RISKS: TX risks added; open questions 6–13; Milestone B = RX+TX; Milestone D = RX+TX together on the UV-PRO.
- TEST-PLAN (new): B1 unit, B2 simulated end-to-end incl. link failures/recovery, B3 safety, D hardware procedure.
- DEPENDENCY-ASSESSMENT, INTEGRATION-REQUESTS: no new runtime deps; source requests 8–10.
- Unchanged: GMRS finding (47 CFR 95.1787 / 95.1733(a)(9)), so the GMRS profile still offers no APRS; all VERIFIED/UNKNOWN labels; existing packages, databases and device connections are preserved.
