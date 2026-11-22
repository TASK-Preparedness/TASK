# Release-readiness assessment (2026-11-21, updated 2026-11-22 for Milestone B)

**Verdict: NOT READY for Public Alpha publication. Ready for maintainer review of the source tree.**

| Area | State | Evidence / gap |
|---|---|---|
| Source completeness | ✅ Complete for every installed module | 0 differences between installed Pi files and this tree (except the intentionally carried notifier). |
| Locally modified files preserved | ✅ | Mesh notifier carried as maintained source; provenance recorded. |
| R.A.I.N. migration preserved | ✅ | byte-identical. |
| License audit | ✅ Draft | GPL-3.0-or-later throughout; third-party notices written; CC-BY-SA alert excluded; needs maintainer confirmation (approval #1, #2). |
| Private data / secrets | ✅ | Scanner: 0 HIGH findings; 45 MEDIUM reviewed (fake test MACs/IPs, government e-mails inside public-domain eCFR/NWS snapshots, fixture paths). Real configs, callsign, MACs of personal devices excluded/redacted. |
| Automated tests | ✅ | Milestone B: 1,805 passed, 0 failed, 15 skipped (x86_64). |
| Debian packages | ⚠️ | Built reproducibly from this tree (Architecture: all), chroot-tested on Debian 13 arm64 under qemu emulation. Not tested on a Pi. Two PROPOSED versions need approval. Placeholder maintainer/Source fields remain. |
| Installer | ⚠️ | Preflight, bundle verification and offline plans exist; the planned argv was executed by a test harness inside the arm64 chroot. The installer itself stays dry run; never run on a Pi. |
| Offline bundle | ❌ | Needs validated packages + clean trixie arm64 dependency closure. |
| Windows | ❌ | Experimental PyInstaller build under Wine only; no Windows test machine; no support claimed. |
| Hardware acceptance | ⚠️ | SDR 0.2.4, Medical Reader 0.3.7, Maps 0.1.1 pending. |
| Docs/community | ✅ Draft | Full doc set, issue templates, Discussions guide; contacts pending (approval #3). |

## Six requested deliverables

| Deliverable | Built? | Why / why not |
|---|---|---|
| TASK-Public-Alpha-Source.zip | **Yes** (pre-alpha source snapshot) | Real, tested source tree. |
| TASK-Release-Documentation.zip | **Yes** | Docs, compatibility matrix, test results, checksums, known issues. |
| TASK-RaspberryPi-Installer.zip | **No** | Installer source is inside the source zip; a separate "installer" download would imply something installable. It performs a dry run only and has never run on a Pi. Will be built once it can install validated packages. |
| TASK-RaspberryPi-Packages.zip | **No** | No arm64 `.deb`s built from this tree have been validated on Debian 13 arm64 hardware. |
| TASK-RaspberryPi-Offline-Bundle.zip | **No** | Needs validated packages and a dependency closure resolved on a clean trixie arm64 system. |
| TASK-Windows-Experimental.zip | **No** | No Windows build exists and no Windows 11 test environment is available. |
