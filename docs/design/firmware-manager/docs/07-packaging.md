# 7. Offline installation and versioned packaging plan

**No .deb or installer has been built. No dependency was installed on the Pi.** Design only; **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**.

## Versioning and payload boundaries

- Documentation release: Firmware Manager Milestone A r1, this ZIP, under 25 MB.
- Proposed first application: `task-firmware` upstream version `0.1.0`, Debian revision initially `0.1.0-1` (final project convention needs confirmation). Target Debian 13 Trixie arm64/Pi 5; pure-Python application can be Architecture: all if build audit confirms no native payload, while qualification and installer target guard remain arm64-only.
- Proposed files: a new `task_firmware` namespace, `/usr/lib/task-firmware/` application resources and `/usr/share/doc/task-firmware/`; launcher registration only through a reviewed extension location/API. No overwrite of other module files, no replacing task-core/compat/comms, Mesh, Radio/APRS or launcher executables.
- Optional board-specific firmware packs and source/license packs version independently by upstream release + registry/recipe revision. Keep out of base app deb until rights and hashes are approved. A fresh base installation with no firmware shows “library empty,” not a network download prompt launched automatically.
- No service unit, autostart, timers, hooks that connect to hardware, background update checks or install-time flash. No root GUI and no global pip.
- Package maintainer identity/email remains **TBD — ask Joshua**. Do not invent one. Local Git commit metadata is not package maintainer metadata.

## r2 pin constraint

The existing Mesh Python client is reported pinned to Meshtastic 2.7.11 [U72]. Do **not** install the Debian 2.6.0 client listed below over it or change task-mesh’s environment. Review system versus private interpreter paths first. The device’s actual firmware version is separate and still unknown. This revision adds no package/dependency changes.

## Dependency candidates, documentary availability only

| Package | Trixie catalog evidence | Plan |
|---|---|---|
| `esptool` | 4.7.0+dfsg-0.1, all [S25] | Initial ESP adapter; qualify Debian DFSG behavior under arm64/Python 3.13, ROM/stub and ESP32/S3. |
| `python3-pyside6.qtwidgets` | 6.8.2.1-4, arm64 [S27] | Reuse installed compatible Qt stack; pulls qtcore/qtgui. No global Qt config changes. |
| `python3-meshtastic` | 2.6.0-1, all [S26] | Optional/reused backup adapter, subject to installed version compatibility; not permission to replace Mesh's client. |
| `python3-serial`, `python3-yaml` | Listed esptool/Meshtastic dependencies [S25,S26] | Resolve Debian dependency closure rather than vendor duplicate global modules. |
| bitstring, cryptography, ecdsa, intelhex, reedsolo | Listed python3 dependencies [S25]; bitstring 4.2.3-1 [S28] | Debian packaged dependencies exist; collect arm64 compiled subdependencies and exact hashes. Not a completed resolver test. |
| bleak, packaging, protobuf, pubsub, requests, tabulate | Listed Meshtastic Python dependencies [S26] | Prefer reviewed existing integration and offline package closure, avoid another communications stack. |
| `adafruit-nrfutil` | Exact queried Debian package absent; full packaging status unknown [S29] | Not needed for initial ESP devices. Future support must use a reviewed deb or isolated application-specific environment built offline from pinned artifacts; never global pip/`--break-system-packages`. |

Catalog availability does not prove packages are installed, compatible with Joshua's current mix, free of resolver removals, or usable without a stub excluded by Debian. No actual dependency solve, ARM run or Qt launch test has occurred. Do not use web docs' pip examples [S06,S13,S23] on this Pi.

## Offline installation process (later approval required)

1. Review actual installed source/version inventory and package file ownership first. Preserve local working changes over canonical sources.
2. Build in a clean Debian 13 arm64 environment on development infrastructure, not the Pi; use system `/usr/bin/python3`. Archive build logs, source, exact version list, Debian copyright/source packages, hashes and a clean install/remove filelist audit.
3. Resolve exact dependency closure against captured installed versions; assemble verified `.deb` packages and source/compliance material in a local offline repository/index. Do not bundle x86 native wheels for arm64. New dependencies require permission; if installed libraries are insufficient, stop with exact conflict, not forced upgrades.
4. Proposed installer reuses the existing audited no-removal/no-downgrade policy after source review: hard-check arm64, Debian 13 Trixie, user/operator intent; show `INSTALL <release-id>` confirmation. Simulate with no removal, reject Remv lines, downgrades, unexpected replacements and changes to protected packages. Re-check actual versions before real action. No apt autoremove, root GUI, global pip or shell interpolation.
5. Offline action may only use the verified local dependency set, not internet apt repositories. Abort missing dependencies instead of fetching. This document is not an installation approval; supply step-by-step copy-paste batches only later.
6. Never restart or enable any existing service in maintainer scripts. Registering a tile must use an approved additive module interface; if unsupported, standalone view remains the safe initial implementation until integration is approved.

## Access and preservation

Joshua reports `dragon` already belongs to `dialout` [U69]. Check device node group/ACL permissions at runtime and fail with clear diagnostics; do not rename users/groups, add groups, chmod all serial devices or change udev/BlueZ globally. Re-enumerated boot interfaces may have different permissions; test on approved spare hardware rather than elevating the GUI.

Filelist/maintainer-script checks must reject any write under `/usr/lib/task-mesh/`, existing sound/data/config paths, task-core service, radio configs, `/library` and the SDR backup. No automatic upgrade/downgrade of existing T.A.S.K. packages, no changes to service enablement policies. `task-firmware` must never pull an older Mesh package just because a bundled dependency list says so.

## App rollback versus device rollback

Archive previous task-firmware deb + own configuration before any later update. Version the vault/registry/journal schemas; additive migrations, backed-up old state and explicit restore instructions, never silently mutate an old immutable image/recipe. Removing just the new package should leave user's vault/backups untouched and remove only its own approved tile registration. No autoremove or collateral module removal. Any reinstall/downgrade is a separately approved operation, not an automatic recovery step. Device firmware recovery is a distinct dangerous action; document 10 applies.
