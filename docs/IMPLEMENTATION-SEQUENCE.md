# Implementation sequence

Each step ends with a review; Pi changes, publishing, flashing and transmitting always
need explicit approval.

**Milestone A — Source consolidation (now)**
1. ✅ Verify archive; diff installed vs. source; merge SDR 0.2.4 branch; import Mesh; carry notifier.
2. ✅ Public docs, notices, templates, scanner, test runner; tests run and recorded.
3. ☐ Maintainer review of this tree and decisions 1–9 in APPROVALS-NEEDED.md.
4. ☐ Collect read-only item #1 (dependency versions) from the Pi.

**Milestone B — Pi packaging**
5. Unify builders into `packaging/debian/build_all.py` (reuse existing deterministic builders, current versions).
6. Build arm64/all `.deb`s on the box; lintian; manifests, SHA-256, build logs.
7. Emulated trixie arm64 chroot: install/upgrade/remove tests (dependency resolution only).
8. Clean-Pi validation on spare media (approval) → only then call packages "tested".

**Milestone C — Universal Pi installer**
9. Real executor (sudo in terminal), progress parsing, error reporting, rollback snapshot.
10. First-launch page; repair/update/uninstall on real packages.
11. Pi 5 then Pi 4 test (approval); Pi 3 / Zero 2 W community tests.

**Milestone D — Offline distribution**
12. Resolve dependency closure on clean trixie arm64; local apt repo; split parts < 25 MB; verify on a disconnected Pi.

**Milestone E — Windows integration (in parallel from Milestone B)**
13. Adopt `task_platform.paths`/`serial_ports` in Launcher, Library, Mesh (Linux behaviour unchanged, tests prove it).
14. Windows backends: Qt notifications/audio, NMEA GPS, background process.
15. PyInstaller onedir + NSIS in GitHub Actions; test on Windows 11 x64 → TASK-Windows-Experimental.

**Milestone F — Public Alpha**
16. Push to GitHub (approval), enable Issues/Discussions/private reporting, attach validated artifacts to `v0.1.0-alpha.1`, call for testers.
