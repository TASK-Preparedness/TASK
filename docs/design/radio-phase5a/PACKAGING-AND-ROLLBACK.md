<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Debian 13 ARM64 packaging and rollback — r3.1 plan
**No installation, upgrade, downgrade, service restart, configuration or package build was performed.** Only this documentation ZIP is built. Commands below describe a later approved procedure, not permission to execute it now.

## Version and dependency baseline
Target Debian 13 trixie / arm64, Python code Architecture: all unless compiled components are added (not proposed). Validate dpkg architecture and VERSION_CODENAME at preflight; do not claim x86 box tests prove Pi execution. Prefer no new runtime dependencies; separate package namespaces, no file replacement.

| Candidate | Dependency/version proposal | Evidence / gate |
|---|---|---|
| task-radio 0.1.0 simulator-host development build | `python3 (>= 3.11)`, `python3-task-comms (= 0.3.1)`, `task-aprs (= 0.1.0)`, `python3-pyside6.qtcore`, `python3-pyside6.qtgui`, `python3-pyside6.qtwidgets` | tomllib requires 3.11 (`/usr/lib/task-aprs/task_aprs/config.py:11`); Qt imports `/usr/lib/task-aprs/task_aprs/ui/main_window.py:8-12`; reviewed exact T.A.S.K. baseline in inventory/versions.txt. Exact '=' pins intentionally conservative until each newer version passes API tests. PySide binary versions not captured: leave Debian dependency unversioned and resolve/test installed Qt package set before release, never invent numbers |
| Future real Core integration | `task-core (= 0.3.0)` for first tested release, optional capability dependency until integration ships | `/usr/lib/python3/dist-packages/task_comms/core.py:14-16,38-75`; Core runtime string 0.2.1 is expected; package pin separate from runtime protocol check |
| python3-task-radio-sim 0.1.0 (only if Q6 approved) | `python3 (>= 3.11)`, `python3-task-comms (= 0.3.1)` for pure shared codec; optional `task-aprs (= 0.1.0)` only if controller harness placed here | Must settle library/harness boundary. No hardware/BlueZ/network dependency, no production package automatically depends on simulator; source/test-only alternative remains open |
| task-mesh 0.3.2 separate release | preserve complete installed 0.3.1 Depends + add `pulseaudio-utils (>= 17.0+dfsg1-2+rpt1)` baseline, and `python3-task-comms (= 0.3.1)` while ABI pinned | audio calls paplay at notifier.py:291-304; installed pulseaudio-utils version `inventory/versions.txt:8`; exact 0.3.1 control/maintainer scripts missing: must collect before final control file; do not drop vendored/protocol dependencies |
| task-launcher | **no new dependency/install/change in B**; 0.3.7 is reviewed optional host baseline | existing task.radio tile already registered. Embedded Radio unsupported without separate patch. If later integration requires it, pin tested launcher version, not imaginary plugin ABI |
| task-core-compat | preserve installed 0.3.0; no replacement or forced reinstall | legacy wrapper content absent; file list/verification only |
| direwolf, bluez, bleak, dbus-fast, serial, gpsd | **no new Depends for simulator**; preserve installed packages | real transport deferred. Existing Direwolf 1.7+dfsg-2+deb13u1 and gpsd 3.25-5+deb13u1 observed, not installed by Radio. Do not retain r3's unnecessary dbus-fast requirement |

This is a justified dependency **plan**, not a finalized Debian control manifest. Missing exact Python/PySide package versions and existing task-mesh control fields are explicit release blockers. Request `dpkg-query -W` and `dpkg-query -s` metadata from Pi later; no installs to resolve them. No pip dependencies, no network resolver on field install. If upstream APIs are changed, release new versions separately (e.g. task-aprs 0.1.1 / comms 0.3.2 subject to approval) and update exact pins only after tests—do not claim current 0.1.0/0.3.1 has proposed safety fixes.

## Files and ABI protection
Radio files only under `/usr/lib/task-radio`, `/usr/bin/task-radio`, `/usr/share/doc/task-radio`; optional sim under `/usr/lib/python3/dist-packages/task_radio_sim`. No core/aprs/comms/mesh/launcher packaged file copied into Radio .deb. Because task-aprs is installed in `/usr/lib/task-aprs`, a carefully scoped import bootstrap/private-path adapter is required; it is not in dist-packages. Do not add global .pth or modify system Python. `task_comms` is importable in dist-packages. Sim dependency allow-list must exclude imported real transport/service factories.

Compatibility preflight on staging validates exact installed versions and selected signatures/constants/return shapes using the source matrix. Use static AST inspection first; safe behavioral checks with fakes and temp dirs only. Generic imports/AprsService constructors may open/create runtime state; never use them as read-only probes. Core protocol check later only under approved live-integration scope; no assignment or login secret collection in diagnostic logs. Unknown API shape/new package version means refuse rather than downgrade it.

## Modified-file protection (dpkg alone is insufficient)
`/usr/lib/...` files are not conffiles; upgrades can overwrite local edits. Parse dpkg --verify **output**, not just exit code. Baseline only notifier.py is modified. Before any future release, hash all target-owned files, compare approved pristine and authoritative local hashes; unknown values **abort before unpack**. Use both installer preflight and package preinst for the target package; maintainer scripts must never stop/restart existing services, change enablement, migrate data or replace another package's files. Install no systemd/autostart/udev/BlueZ config. Never reset user files to shipped defaults.

Unknown modifications anywhere in planned target paths => abort and request review. Archive/snapshot user settings and source hashes in private (0700/0600) rollback store; never include these in distributed artifacts. Do not assume dpkg preserves custom /usr/lib notifier. A package guard limited to Radio cannot protect a later unrelated task-mesh upgrade: document the independent Mesh guard requirement.

## Approved-install procedure (future, staging first)
1. User explicitly approves exact package/version/file changes and downtime separately. Obtain known-good old .debs and checksums offline; verify new checksum, package contents and scripts before invoking root. No automatic downloads.
2. Snapshot package versions + dpkg --verify output; current core/gpsd/Mesh active/enabled states; module/config hashes; notifier, backup and WAV bytes/hashes; user protocol assignments. Keep originals and tar with private permissions. Radio does not need to stop any service; if simulator test needs one stopped, fix isolation instead.
3. Gate OS/arch/version/signatures; inspect `dpkg-deb --info`/`--contents` and maintainer scripts. Abort on files owned by installed modules, units/autostart, unknown changes, removals/upgrades/downgrades. Preview `apt-get -s --no-remove install ./task-radio_0.1.0_all.deb` plus optional exact sim .deb; review every Inst/Remv. Reject any change beyond approved new Radio/sim packages. Don't run this on Pi during review.
4. Only after approved preview on staging: offline `apt-get --no-download --no-remove install ./task-radio_0.1.0_all.deb` (and optional sim .deb explicitly chosen). No --allow-downgrades, no autoremove, no purge, no service enabling. Dependency missing => stop; never 'fix' via unattended install. Controlled GUI launch starts with TX disabled and simulation-only.
5. Compare snapshots: Core/gpsd/Mesh PIDs/service state/enablement unchanged; notifier/WAV hashes byte-identical; old radio tile unchanged; only approved package additions. Run sim with denied device/network access; do not launch actual Bluetooth or Direwolf clients. Report results and stop if any mismatch.

## Radio rollback (future explicit approval)
1. Close Radio/sim process; ensure application work canceled. Preserve private user data; do not delete shared DBs.
2. Preview `apt-get -s remove task-radio` (and optional `python3-task-radio-sim` only if installed by this release). Review removal set. Then explicit approved `apt-get remove task-radio` with only approved package names; no autoremove/purge. '--no-remove' is for install previews, not removal execution.
3. Retain Radio config/state in user home; do not rewrite Core/aprs/launcher settings. Compare package/service/hash snapshots: only those newly added packages removed. Any unrelated difference is a failed rollback, stop rather than auto-repair.

## Independent Mesh 0.3.2 release / rollback
Not a Radio dependency or bundled side effect. Use authoritative notifier byte-for-byte as the initial 0.3.2 source base, preserve user's WAV path, keep settings filters, declare sound attribution and required paplay dependency. Adding `/usr/share` default fallback is a separately reviewed behavior change, not already present. No package writes into /home/<user>.

Before authorized Mesh upgrade, validate known notifier/WAV hashes and save exact working 0.3.1 .deb + patched notifier + pre-audio-backup + WAV + user configuration. Stage tests and preserve existing service enablement; package scripts do not restart service. User later explicitly approves any necessary restart and real incoming-message regression test.

Rollback must not reinstall stock 0.3.1 alone: it lacks the working audio patch. Preferred: prebuilt approved audio-preserving rollback package with clearly newer local version (e.g. 0.3.2+rollback1) from saved authoritative sources, after review/testing. Alternative reinstall saved 0.3.1 **and immediately restore the backed-up working notifier and WAV before any approved restart**, only after explicit downgrade/restore approval. No automatic downgrade/restore code during this review. Never restore `.pre-audio-backup` as the live notifier. Preserve private file ownership/modes, verify hashes before/after and retain rollback evidence. A pristine 0.3.1 package alone is not recovery.

## Packaging pass/fail matrix (NOT RUN)
| Gate | Pass | Fail/stop |
|---|---|---|
| OS/ABI/dependencies | trixie arm64, reviewed versions/signatures and Qt set; no downloads | missing version evidence, unknown ABI, install needs unrelated changes |
| Contents | new module files only; docs/license complete | replaced core/aprs/mesh/launcher files, unit/autostart/udev additions |
| Modified target | all known approved hashes, private backup verified | unknown local edits or missing backup |
| Install preview | only selected Radio/sim package additions | removal/upgrade/downgrade of installed packages |
| Runtime isolation | sim-only, no real sockets/devices, TX off on startup/restart | physical factory imported or saved enable flag restored |
| Service invariance | core/gpsd/Mesh active/enablement/PIDs unchanged | any start/stop/restart/reconfiguration |
| Mesh preservation | notifier/WAV original hashes, sound settings preserved | stock notifier overwrite, changed WAV/license absent |
| Removal | only selected new packages removed; user/shared data retained | autoremove/purge, shared data touched |
| Mesh rollback rehearsal | audio-preserving sources and hashes restored before approved restart | stock 0.3.1 reinstalled without patch, unplanned service policy change |
