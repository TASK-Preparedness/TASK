<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# SPEC — APRS (Phase 4J)
* Receive through an existing Direwolf (AGW/KISS); never start/configure Direwolf as root; never edit direwolf.conf.
* TX only amateur, licensed callsign configured, explicit user action, comms txpolicy + hash-chained audit (exists).
* Messages feed the comms notification store as source "aprs" (badge reuse), no merge with mesh identities.
* GMRS driver stays simulated until hardware approval. Tests: no TX without callsign/explicit action; audit entry; RX parse.
