# task-aprs 0.1.0

Two-way amateur APRS through an already running Direwolf (AGW preferred, KISS fallback) and a separate GMRS
data profile (radio-integrated only). Never starts, configures or keys Direwolf/radios itself; every
transmission is one explicit user action checked by `task_comms.txpolicy` and audited.
Indicator is **QUEUED** (frame in Direwolf's queue); a falling queue count is queue progress, **not RF proof**.
See docs/GMRS-HARDWARE-RESEARCH.md for the GMRS blocker.
