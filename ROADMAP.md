# Roadmap

Milestones for the first public release. Dates are not promised; each step is
gated on real tests and maintainer approval.

> **EXPERIMENTAL ALPHA — NOT VALIDATED ON A PHYSICAL RASPBERRY PI.**
> A project-wide license is still pending owner approval. Nothing has been
> published to GitHub at the time this file was written.

| Milestone | Goal | State |
|---|---|---|
| A — Source consolidation | One public source tree matching the installed Pi, preserved Mesh audio change and R.A.I.N. migration, docs, license audit, secrets scan | **done** in this tree (unpublished staging) |
| B — Raspberry Pi packaging | Reproducible arm64 `.deb`s for every module, manifests, checksums, build logs, lintian; install/upgrade/remove tested on a clean Pi | **packaging built**; emulated Debian 13 arm64 chroot tested; **not validated on a physical Pi**. Package updates task-mesh 0.3.2~alpha1, task-console 0.2.1~alpha1 and launcher 0.3.8 approved for isolated builds and volunteer testing only |
| C — Universal Pi installer | Turn the dry-run installer into a real one (privileged steps via sudo in a terminal, no root GUI), first-launch setup, repair/update/uninstall, tested on Pi 5 and Pi 4 | skeleton exists (**dry run only**) |
| D — Offline distribution | Dependency-complete offline bundle for Debian 13 arm64, verified on a disconnected Pi | not started |
| E — Windows integration | Platform layer adoption, Windows backends, experimental PyInstaller + NSIS build tested on Windows 11 x64 | groundwork only; **no Windows support in this alpha** |
| F — Public Alpha | Publish source and experimental artifacts on GitHub Releases, enable Issues/Discussions, recruit volunteer Pi testers | **in preparation** (this branch). Publication awaits owner approval of the license and exact release contents |

Module work outside these milestones (each separately approved):
* task-mesh 0.3.2~alpha1, task-console 0.2.1~alpha1, launcher 0.3.8 — approved for packaging and isolated testing; not Pi-validated.
* task-radio / Phase 5A Milestone B — two-way APRS, simulator first, transmit off by default (not approved to code).
* Firmware Manager — offline vault and explicit-confirmation flashing, first device Heltec V3 915 MHz (not approved to flash).
* Mission Planner, Weather decoders — design.
