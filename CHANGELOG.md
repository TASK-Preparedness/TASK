# Changelog

All notable changes to the T.A.S.K. platform repository. Individual Debian
packages keep their own `changelog` files under each module's `packaging/`.

## [Unreleased] — Milestone B (2026-11-22): packaging, installer, Windows groundwork

Nothing here was installed on, or validated on, a Raspberry Pi. Nothing was published.

### Fixed
* Mesh AT-15 crash-safety test: it used fixed 2026-09-21 timestamps, which the 30-day start-up
  retention prune began deleting around 2026-10-21. The test now uses a frozen clock, and a
  regression test pins the 30-day retention. **Mesh retention code unchanged.** (KNOWN-ISSUES.md)
* Console `test_75`: Debian 13's `posix_local` pip scheme turns `--prefix /usr/local` into
  `/usr/local/local`. The test now uses `--root` only. `install-console.sh` is marked developer-only
  and refuses to shadow an installed task-console .deb.

### Added
* `packaging/debian/`: one reproducible builder for all ten packages, with safety gates and a
  cross-package file-conflict check; payload verification against the delivered debs and the Pi's
  installed files; an emulated Debian 13 arm64 chroot test harness (install/remove/purge, upgrade, installer plan).
* Installer 0.2.0.dev0: revision-code model detection (read-only), stricter profile on
  model/revision mismatch, bundle loading with checksum verification, preflight (downgrade refusal,
  backup of locally modified files that will be overwritten, shadowing and legacy warnings), offline
  update/repair/recovery plans, `--bundle`/`--dpkg-verify` in TUI and wizard, a dry-run fixture
  matrix (18 hosts). Still **dry run only**.
* `platform/` 0.2.0.dev0: config (TOML, atomic save), device discovery (known USB IDs, never opens
  ports), offline resources (read-only scan, manifest verify), injectable Windows serial listing.
* `installers/windows/`: proposed launcher portability patch, PyInstaller spec, NSIS and WiX
  scripts, build script, simulated and Wine smoke tools. Experimental and untested; **no Windows support claimed.**

### Proposed versions (need approval; not installed anywhere)
* task-mesh **0.3.2~alpha1**: 0.3.1 plus the maintained audible-alert notifier (payload equals the Pi except changelog).
* task-console **0.2.1~alpha1**: adds the missing `python3-pyside6.qtnetwork` dependency (packaging-only).

### Not changed
* Every other package is rebuilt byte-identical to the delivered/Pi-installed version (comms 0.3.1,
  core 0.3.0, compat 0.3.0, aprs 0.1.0, sdr 0.2.4, launcher 0.3.7, maps 0.1.1, resources 0.2.4).
* LICENSE, THIRD_PARTY_NOTICES, copyright headers and debian/copyright licence fields (licence audit runs separately).

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
