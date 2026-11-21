# T.A.S.K. modules — verified inventory

Inventory date: 2026-11-21. Evidence sources:

1. **Installed-source archive** collected read-only from the development Pi on
   2026-11-08 (`task-r3-sources-20261108-112630.tar.gz`, 631 files, SHA-256
   `f479d7713707ede16dd39668487762b3b07f5ad65810f014057430b7a3565d2b`, re-verified).
   It contains the installed package files, `dpkg --verify` output and package versions.
2. **Development source trees**, compared file-by-file with the installed files.
   Result: every installed Python file of every T.A.S.K. package is byte-identical
   to the source in this repository, except the intentional Mesh notifier change,
   which this repository now carries as maintained source (see below).
3. **Automated test runs** recorded in [TESTING.md](TESTING.md).

A launcher tile alone never counts as an implementation.

## Maturity scale

| Level | Meaning |
|---|---|
| stable | Released, hardware-accepted, no known blocking issues. *(No module is stable yet.)* |
| tested | Installed and in daily use on the development Pi 5, and its automated tests pass. |
| experimental | Code exists and installs; automated tests pass, but a physical acceptance test, a feature milestone or a known issue is outstanding. |
| incomplete | Partially implemented; does not do what its name suggests yet. |
| planned | Designed (or just a tile); no usable code. |
| unavailable | Not available on that platform. |

## Summary

| Module (tile) | Repo path | Debian package | Version on Pi | Maturity |
|---|---|---|---|---|
| T.A.S.K. Core | `task_core/`, `task_core_migrate/`, `share/`, `packaging/task-core/` | task-core | 0.3.0 | tested |
| R.A.I.N. compatibility | `task_core_migrate/` + legacy names | task-core-compat | 0.3.0 | tested |
| Shared comms library | `comms/` | python3-task-comms | 0.3.1 | tested |
| Launcher (+ Files, System, App Manager) | `launcher/` | task-launcher | 0.3.7 | tested |
| Mesh Network | `mesh/` | task-mesh | 0.3.1 + maintained audio change | tested |
| Maps & GPS | `maps/` | task-maps | 0.1.1 | experimental |
| Radio / APRS | `aprs/` | task-aprs | 0.1.0 | experimental |
| SDR Studio | `sdr/` | task-sdr | 0.2.4 | experimental |
| Offline Library & Medical Reader | `resources/` (+ launcher medical view) | task-resources | 0.2.4 | experimental |
| Devices | `console/` | task-console | 0.2.0 | experimental |
| Medical (built-in reference finder) | `launcher/task_launcher/services/medical.py` | task-launcher | 0.3.7 | experimental |
| Weather | `launcher/task_launcher/services/weather.py` | task-launcher | 0.3.7 | incomplete |
| Notifications | `comms/task_comms/notifications.py`, `mesh/task_mesh/hub/notifier.py` | python3-task-comms, task-mesh | 0.3.1 | tested |
| Hardware discovery & ownership | `task_core/enumerator.py`, `exclusion.py`, `comms/task_comms/ownership.py` | task-core, python3-task-comms | 0.3.0 / 0.3.1 | tested |
| Background services | `packaging/task-core/task-core.service`, `mesh/packaging/systemd/task-mesh-service.service` | task-core, task-mesh | — | tested |
| Platform abstraction | `platform/` | (not packaged) | 0.1.0.dev0 | experimental |
| Raspberry Pi installer | `installers/raspberry-pi/` | (not packaged) | 0.1.0.dev0 | experimental (dry run only) |
| Mission Planner | — (tile `060-mission.toml` has `status = "planned"`) | — | — | planned |
| Firmware Manager | `docs/design/firmware-manager/` (documents only) | — | — | planned |
| Two-way Radio (task-radio, Phase 5A) | `docs/design/radio-phase5a/` (documents only) | — | — | planned |
| Offline resources (maps, ZIM, medical) | none bundled | — | — | unavailable (user-supplied) |
| Windows build | `platform/` groundwork only | — | — | unavailable |

## Details

### T.A.S.K. Core — task-core 0.3.0, task-core-compat 0.3.0 (tested)
* **Installed at:** `/usr/lib/python3/dist-packages/task_core`, `task_core_migrate`; `/usr/bin/task-core`, `task-core-admin`; `/usr/sbin/task-core-migrate`; `/usr/lib/task-core/{modules,devices}`; `/usr/lib/systemd/system/task-core.service`.
* **Depends:** python3 (≥ 3.11), python3-yaml (≥ 6); optional pyudev.
* **Does:** USB/serial device enumeration (udev), device→module assignment, exclusive ownership/locking, accounts, sessions, protocol v2 socket API, terminal admin CLI.
* **R.A.I.N. migration:** `task-core-migrate` migrates the earlier R.A.I.N. (`rain-core`) configuration to `/etc/task` (the Pi has `/etc/task/MIGRATED`); task-core-compat keeps legacy command names (e.g. `rain-core-admin`). Preserved unchanged.
* **Known issues:** `task_core.__version__` reports `0.2.1` while the package is 0.3.0; root `pyproject.toml` also says 0.2.1. A lock-ownership fix (0.3.1, branch `phase4c-fix-lock`) exists in development history but is **not** installed and is not included here pending review.
* **Tests:** 178 collected (see TESTING.md).

### Shared communications library — python3-task-comms 0.3.1 (tested)
* **Installed at:** `/usr/lib/python3/dist-packages/task_comms`.
* **Does:** desktop notifications (D-Bus), ownership coordination, transmit-policy guard (`txpolicy.py`), feeds, audit log, APRS helpers.
* **Known issues:** builder script `release/build_release.py` still names 0.3.0; the installed 0.3.1 matches this source.

### Launcher — task-launcher 0.3.7 (tested)
* **Installed at:** `/usr/share/task-launcher` (code + `apps.d` tiles), `/usr/bin/task-launcher`.
* **Depends:** python3 (≥ 3.13), PySide6 ≥ 6.8 (QtCore/Gui/Widgets/Svg); recommends fonts-inter, qt6-wayland, xdg-utils.
* **Does:** dashboard tiles from `apps.d/*.toml`, launches modules, built-in Files, System (read-only status), App Manager, Devices fallback, Medical reference finder, Weather status, read-only Kiwix library fallback.
* **Known issues:** Devices tile still prefers the legacy `/usr/local/bin/task-console` path; 0.3.7 Medical Reader crash fix awaits its Pi acceptance test; tile versions in `apps.d` are tile-manifest versions, not package versions.
* **Icons:** Lucide (ISC) / Feather (MIT) — see THIRD_PARTY_NOTICES.md.

### Mesh Network — task-mesh 0.3.1 + maintained audible alert (tested)
* **Installed at:** `/usr/lib/task-mesh/task_mesh` (with vendored meshtastic 2.7.11, meshcore 2.3.15, pycayennelpp 2.4.0, pyserial-asyncio-fast 0.16), `/usr/bin/task-mesh`, `task-mesh-service`, `task-mesh-notify-setup`, user unit `task-mesh-service.service` (active on the Pi, **not** enabled at boot — preserved policy).
* **Depends:** PySide6 ≥ 6.8, python3-serial, -protobuf, -pubsub, -pyudev, -requests, -tabulate, -yaml, -packaging, -pycryptodome, -jeepney, qt6-wayland.
* **Does:** Meshtastic over USB serial (Heltec V3 verified), MeshCore protocol support, message database, background hub service, desktop notifications.
* **Audible alert (hand-modified on the Pi, now maintained source):** `mesh/task_mesh/hub/notifier.py` is the installed Pi version (SHA-256 `2864d242…bbe1a`); the original package version (`notifier.py.pre-audio-backup`, SHA-256 `3a8f6145…20b72`) equals task-mesh 0.3.1 source. Change: desktop notification always suppresses its own sound, and the notifier plays `~/.local/share/task-mesh/sounds/mesh-alert.wav` with `/usr/bin/paplay` (argv list, detached, no shell) when sound is on. Diff: `docs/provenance/mesh-notifier-audio.diff`.
* **WAV not shipped:** derived from a CC-BY-SA-3.0 sound; users generate it with `scripts/generate-mesh-alert.sh` (see THIRD_PARTY_NOTICES.md).
* **Known issues:** package version still 0.3.1 although the notifier differs from the 0.3.1 .deb — a 0.3.2 release is proposed (needs approval); debian/copyright lists `Source: https://example.invalid/task-mesh` and holder "T.A.S.K. Mesh Operations contributors" (needs maintainer decision); test runner previously extracted only the meshtastic wheel (fixed here).

### Maps & GPS — task-maps 0.1.1 (experimental)
* **Installed at:** `/usr/share/task-maps`, `/usr/bin/task-maps`. **Depends:** PySide6; recommends gpsd.
* **Does:** own MBTiles renderer, gpsd position (u-blox 7 on the Pi via gpsd), waypoints, tracks, GPX, download-source policy (`sources.d`).
* **Known issues:** no map data bundled; physical acceptance results for all of Joshua's 12 Maps tests are not in the inventory, so it stays experimental.

### Radio / APRS — task-aprs 0.1.0 (experimental)
* **Installed at:** `/usr/lib/task-aprs`, `/usr/bin/task-aprs`. **Depends:** PySide6, python3-task-comms ≥ 0.3.0; uses an existing, user-configured Direwolf (AGW/KISS).
* **Does:** APRS receive and history through Direwolf; transmit only by explicit operator action; separate GMRS data profile (simulated driver).
* **Known issues:** two-way APRS (Phase 5A Milestone B) not implemented; BTECH UV-PRO Bluetooth KISS **unverified**; transmit off by default and gated by callsign attestation.

### SDR Studio — task-sdr 0.2.4 (experimental)
* **Installed at:** `/usr/lib/task-sdr`, `/usr/share/task-sdr/schema`, `/usr/bin/task-sdr`.
* **Depends:** PySide6 incl. QtMultimedia, python3-numpy, python3-scipy, SoapySDR + RTL-SDR module.
* **Does:** receive-only WFM/NFM/AM/USB/LSB, spectrum, waterfall, scanner, frequency overlays (dataset-free framework).
* **Known issues:** 0.2.4 audio pipeline awaits Pi hardware acceptance; `sdr/pyproject.toml` says 0.2.2 while `__version__` is 0.2.4.

### Offline Library & Medical Reader — task-resources 0.2.4 (experimental)
* **Installed at:** `/usr/share/task-resources`, `/usr/bin/task-resources`. **Depends:** PySide6, python3-libzim; recommends QtWebEngine.
* **Does:** ZIM/PDF/EPUB/text reader, read-only index, crash guard, light (non-WebEngine) reader.
* **Known issues:** awaits Pi acceptance of the Medical Reader crash fix; no content bundled; Kiwix/ZIM libraries on the Pi are never modified.

### Devices — task-console 0.2.0 (experimental)
* **Installed at:** `/usr/lib/task-console`, `/usr/bin/task-console`. **Does:** device list/assignment UI over task-core.
* **Known issues:** legacy pip-based `install-console.sh` footprint test fails on Debian 13's pip (`/usr/local/local/…`); the .deb is the supported path.

### Weather (incomplete) and Mission Planner (planned)
* Weather shows only the presence of decoders and the age of local data; there is no decoder integration or forecast engine.
* Mission Planner is a tile with `status = "planned"` and no source code.

### Firmware Manager and two-way Radio (planned)
Design documents only, under `docs/design/`. No flashing code exists. Both remain
gated on explicit maintainer approval; the installer never flashes or transmits.
