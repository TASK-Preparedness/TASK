# Changelog

All notable changes to the T.A.S.K. platform repository. Individual Debian
packages keep their own `changelog` files under each module's `packaging/`.

## [Unreleased] — Prominent safety warnings, history cleanup (2026-11-25)

Prepared for owner approval. Nothing was published, tagged or pushed. The
approved package files were not rebuilt, and no software was changed.

### Changed
* README: a "READ FIRST" warnings block at the top states that this is an
  experimental alpha that is not validated on a physical Raspberry Pi, that
  T.A.S.K. is receive-only by default and must never transmit unless a licensed
  operator explicitly tells it to, and that hardware not listed as tested is
  **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**.
* The unpublished development commits were rebuilt on top of the existing
  public `97e2413` commit without the internal `docs/engineering-history/`
  folder. The tree contents are unchanged.

## [Unreleased] — Optional Buy Me a Coffee funding (2026-11-24)

Prepared for owner approval. Nothing was published, tagged or pushed.
Nothing was installed on a Raspberry Pi. The approved package files were
not rebuilt.

### Added
* Voluntary funding option at <https://buymeacoffee.com/t.a.s.k.prepardness>
  (URL used exactly as provided). [README.md](README.md) has a Buy Me a
  Coffee button and a [Support T.A.S.K.](README.md#support-task) section.
  `.github/FUNDING.yml` lists the same URL. Contributions are entirely
  optional, do not restrict software features, and support development
  time, equipment, testing, maintenance and future improvements.

## [Unreleased] — Public experimental alpha, Option A applied (2026-11-24)

Prepared for owner approval. Nothing was published, tagged or pushed.
Nothing was installed on a Raspberry Pi. The packages have **not** been
validated on a physical Raspberry Pi.

### Added
* Option A licensing documents: verbatim GNU GPL v3 ([LICENSE](LICENSE)),
  [TRADEMARK.md](TRADEMARK.md), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md),
  [REUSE.toml](REUSE.toml), [PROJECT-COMMITMENTS.md](PROJECT-COMMITMENTS.md),
  and [docs/MESH-BRIDGE-MILESTONE.md](docs/MESH-BRIDGE-MILESTONE.md) (a future,
  non-blocking plan). Own code is GPL-3.0-or-later. The `task-mesh` package
  as a whole is GPL-3.0 because it bundles meshtastic (GPL-3.0-only).
  Contributions use DCO sign-off; there is no CLA.
* [SECURITY.md](SECURITY.md): report vulnerabilities through GitHub private
  vulnerability reporting. General support is through GitHub Issues. There
  is no project email address. A donation link was added later the same day
  (see the section below).

### Changed
* CONTRIBUTING.md records inbound=outbound GPL-3.0-or-later licensing and DCO
  1.1 sign-off.
* INSTALL.md, docs/VOLUNTEER-TESTING.md and KNOWN-ISSUES.md carry the
  volunteer-test 2026-11-23 package versions and SHA-256 values, and document
  the task-mesh `pulseaudio-utils` Recommends limitation. Every package is
  labelled experimental and not validated on a physical Raspberry Pi.
* `docs/ARCHITECTURE.md`: a private-network example access-point address replaced
  with TEST-NET-1 `192.0.2.1`.
* Internal `docs/engineering-history/` is no longer in the public tree. The
  five SDR Studio notes that already ship inside the `task-sdr` package are
  kept under `sdr/docs/`.

### Known limitation (unchanged packages)
* The already-built volunteer-test `.deb` files, and the packaging source
  that reproduces their SHA-256 checksums, still contain the placeholder
  maintainer field `TBD-maintainer-email`. That field is not a contact
  address. A later approved rebuild can replace it; this alpha does not
  rebuild those packages.

## [Unreleased] — Public experimental alpha preparation (2026-11-23)

Nothing here was installed on, or validated on, a Raspberry Pi. Nothing was
published. At that date the project-wide license was still pending owner
approval (resolved 2026-11-24; see the section above).

### Added
* Public-alpha documentation set for volunteer testers: [SAFETY.md](SAFETY.md),
  [SUPPORT.md](SUPPORT.md), expanded [INSTALL.md](INSTALL.md) (spare SD card,
  one command at a time, SHA-256 verification, uninstall and rollback), and a
  volunteer test-report issue template.
* README and related docs now label this tree **EXPERIMENTAL ALPHA — NOT
  VALIDATED ON A PHYSICAL RASPBERRY PI**, and state that Windows is not
  supported.
* Top-level [LICENSE](LICENSE) was still an explicit `LICENSE PENDING OWNER APPROVAL`
  placeholder on this date. Historical GPL headers and per-module LICENSE files were **not**
  rewritten then. Option A was applied the following day.

### Changed
* CONTRIBUTING and SECURITY no longer treat GPL-3.0-or-later as an approved
  project-wide license. Reporting paths keep the maintainer e-mail as a
  placeholder.
* Bug-report and hardware issue templates ask for Pi model, revision, OS and
  package versions.

## [Unreleased] — Volunteer test round 1 (2026-11-23)

Approved on 2026-11-23 for packaging, building and isolated testing only. Nothing was installed on the
development Pi, and nothing was published.

### Changed
* **task-launcher 0.3.8**: the Windows portability changes (paths, privilege check, temp names, manifest
  owner check) are merged into `launcher/`, so `installers/windows/patches/` is gone. The Devices tile prefers
  the packaged `/usr/bin/task-console`. Linux behaviour is otherwise unchanged (launcher suite 326 passed, 13 skipped).
* **task-mesh 0.3.2~alpha1** and **task-console 0.2.1~alpha1**: changelogs finalised (alpha, approved for
  testing). task-mesh now Recommends pulseaudio-utils (paplay, audible alert) and Suggests ffmpeg and sound-theme-freedesktop.
* Builders: the package root directory mtime is normalised too. Without this, a build started before
  SOURCE_DATE_EPOCH leaked the build time.

### Added
* `docs/VOLUNTEER-TESTING.md`: a guide for spare-card Pi 5 / Debian 13 arm64 testers, with a consistency test.
* `packaging/debian/check_baseline.py` + `reference/pi-dpkg-baseline-20261122.txt`: Depends/version floors
  checked against the Pi's reported packages (0 violations).
* Chroot scenarios: rollback to the Pi's previous versions; the volunteer guide's commands.
* Installer fixture for the development Pi exactly as reported (Pi 5 Rev 1.0, d04170, arm64, Debian 13.6, ID=debian).


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
