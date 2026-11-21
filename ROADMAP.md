# Roadmap

Milestones for the first public release. Dates are not promised; each step is
gated on real tests and maintainer approval.

| Milestone | Goal | State |
|---|---|---|
| A — Source consolidation | One public source tree matching the installed Pi, preserved Mesh audio change and R.A.I.N. migration, docs, license audit, secrets scan | **in progress** (this tree) |
| B — Raspberry Pi packaging | Reproducible arm64 `.deb`s for every module, manifests, checksums, build logs, lintian; install/upgrade/remove tested on a clean Pi | not started |
| C — Universal Pi installer | Turn the dry-run installer into a real one (privileged steps via sudo in a terminal, no root GUI), first-launch setup, repair/update/uninstall, tested on Pi 5 and Pi 4 | skeleton exists (dry run) |
| D — Offline distribution | Dependency-complete offline bundle for Debian 13 arm64, verified on a disconnected Pi | not started |
| E — Windows integration | Platform layer adoption, Windows backends, experimental PyInstaller + NSIS build tested on Windows 11 x64 | groundwork only |
| F — Public Alpha | Publish source and validated artifacts on GitHub Releases, enable Issues/Discussions | not started |

Module work outside these milestones (each separately approved):
* task-mesh 0.3.2 — release the maintained audible-alert notifier.
* task-radio / Phase 5A Milestone B — two-way APRS, simulator first, transmit off by default.
* Firmware Manager — offline vault and explicit-confirmation flashing, first device Heltec V3 915 MHz.
* Mission Planner, Weather decoders — design.
