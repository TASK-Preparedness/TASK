# Changelog

All notable changes to the T.A.S.K. platform repository. Individual Debian
packages keep their own `changelog` files under each module's `packaging/`.

## [Unreleased] — Public Alpha preparation (Milestone A, 2026-11-21)

### Added
* Consolidated public source tree: core, compat, comms, launcher 0.3.7, resources 0.2.4,
  maps 0.1.1, aprs 0.1.0, console 0.2.0, sdr 0.2.4 and mesh 0.3.1 in one repository.
* `platform/` — experimental cross-platform abstraction layer (paths, read-only serial
  discovery, detached processes, capability table) with tests.
* `installers/raspberry-pi/` — pre-alpha installer: read-only detection, compatibility
  matrix, Complete/Custom/Minimal planning, repair/update/uninstall plans, TUI and PySide6
  wizard. **Dry run only.** Simulation tests only.
* `scripts/generate-mesh-alert.sh` — user-side recipe for the CC-BY-SA mesh alert.
* Public documentation set, issue templates, Discussions guide.

### Changed
* Mesh notifier: the hand-modified audible-alert notifier from the development Pi is now
  the maintained source (`mesh/task_mesh/hub/notifier.py`); provenance in `docs/provenance/`.
* `mesh/tools/run_tests_debian.sh` now extracts all four pinned vendored wheels (MeshCore tests needed meshcore).
* `release/common/tests/test_installers.py` expects six release configs after merging the SDR 0.2.4 branch.
* SPDX headers added to ten scripts that lacked them.
* MAC addresses redacted from Phase 5A design documents.

### Not changed
* No package versions were bumped; no module behaviour was changed except the notifier carried over from the Pi.
