<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Radio r3.1 documentation changes
Baseline commit ad641ea (r3); installed-source inventory replaces all pre-install interface assumptions. Review date 2026-11-08 EST.

* Verified supplied SHA-256, 593 installed files/632 members and all three notifier/backup/WAV hashes; safe extraction; no installed code imported/executed.
* Added exact API matrix plus complete static signature/hash index across Core, comms, APRS, selected Mesh and launcher interfaces.
* Corrected Direwolf ownership/generated-config claim: task-aprs only connects, config absent from archive, no Direwolf process; observed 8000/8001 listeners unassigned. Ports remain unknown, not 'confirmed defaults'.
* Corrected process-local comms vs central broker, Core assignment vs physical lease, Mesh lock namespace, one-shot CoreClient event streaming limitation, runtime/package Core version distinction and gpsd active/disabled state.
* Removed scan API declaration and automatic RF-ack assumption. Optional simulator peer auto-response OFF. No duplicate codec/controller/policy/scheduler, no silent Q2 retry default.
* Identified installed schedule 30/90/210 rather than Q2, message-ID reset/rollover and missing ack freshness/channel/epoch checks; direct Bluetooth KISS rejected by current shared policy/PTT contract.
* Added actual launcher existing task.radio conflict and absence of generic Radio embedding/plugin API; leave tile and launcher untouched.
* Recorded persisted GMRS TX/auto-reply switches without treating them as authorization or exposing callsign. No private databases/config contents bundled.
* Added guarded final-write proposal with one-use tickets, monotonic expiry/kill, cancellation/restart/no-replay and honest TNC de-key limits; no implementation yet.
* Expanded simulator/safety/packaging test matrices with pass/fail criteria and NOT RUN status; implementation sequence gated on explicit approval.
* Upstream sound CREDITS identifies Tim/corsica_s, Debian per-file copyright supports CC-BY-SA-3.0. Exact recipe preserved, byte hashes matched; audio-preserving independent 0.3.2/rollback plan.
* Exact dependency plan pins reviewed T.A.S.K. packages; missing Qt/Mesh packaging metadata explicit blocker, unnecessary simulator dbus/serial/Bluetooth dependencies removed.
* Verdict CONDITIONAL GO only for authorized offline simulation; NO-GO for installation, physical connection or RF. Seven original questions reproduced unchanged.

No Pi access, service changes, Milestone B implementation, module source edits, firmware-manager worktree changes, installs or RF actions. This commit changes documentation only. Source archive and WAV excluded from deliverable ZIP.
