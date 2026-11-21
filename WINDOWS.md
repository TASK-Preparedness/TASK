# T.A.S.K. on Windows — architecture and status

> **Status: unavailable.** No Windows build exists and nothing has been run on
> Windows. This document is the plan, plus the shared groundwork that already
> exists in `platform/`. Windows compatibility will only be claimed after a
> build has been made and tested on Windows 11 x64.

Target: **Windows 11 x64**, native PySide6 UI shared with the Raspberry Pi version.

## Principles

1. Share code: the Qt UI, protocol logic (Meshtastic, MeshCore, APRS/AX.25/KISS,
   DSP, ZIM/PDF reading, map rendering) is already platform-neutral Python.
2. Isolate OS-specific code behind `task_platform` interfaces; Linux behaviour must not change.
3. Same safety rules: read-only discovery, no automatic transmit, no auto-start,
   no firmware flashing from the installer, no shell strings.

## Platform abstraction layer (`platform/task_platform`, 0.1.0.dev0)

| Area | Linux backend | Windows backend | Status (Linux / Windows) |
|---|---|---|---|
| File paths | XDG (`~/.config`, `~/.local/share`) | `%APPDATA%\TASK\<app>`, `%LOCALAPPDATA%\TASK\<app>\{data,cache,logs}` | verified / implemented, untested |
| Serial ports | `/sys/class/tty` + `/dev/serial/by-id` (never opened) | pyserial `list_ports` (registry, not opened) | implemented / implemented, untested |
| Process launch | argv + `start_new_session` | argv + `DETACHED_PROCESS`/`CREATE_NEW_PROCESS_GROUP` | verified / implemented, untested |
| USB discovery | sysfs | SetupAPI via pyserial / WMI (planned) | implemented / planned |
| Bluetooth | BlueZ D-Bus (bleak/dbus-fast) | bleak WinRT backend; classic SPP through the virtual COM port | implemented / planned |
| GPS | gpsd client | direct NMEA over COM port (no gpsd on Windows) | verified / planned |
| SDR | SoapySDR + RTL-SDR | SoapySDR or librtlsdr with WinUSB driver (user installs via Zadig) | verified / planned |
| Notifications | freedesktop D-Bus (`task_comms.notifications`) + `paplay` alert | Qt `QSystemTrayIcon.showMessage` + `QSoundEffect` for the alert | verified / planned |
| Background services | systemd user unit (never auto-enabled) | per-user background process started from the launcher; optional Task Scheduler entry only on explicit opt-in | verified / planned |
| Permissions | `dialout` group, polkit-free | none needed for COM ports; driver install is a user/admin action | verified / planned |
| Logging | journald / files under XDG state | rotating files under `%LOCALAPPDATA%\TASK\<app>\logs` | verified / planned |
| Configuration | TOML under XDG config | same TOML under `%APPDATA%\TASK` | verified / planned |

The table is also code: `task_platform.capabilities.CAPABILITIES`, with a test that
fails if any Windows entry is marked verified.

## Per-module plan

| Module | Linux-specific parts today | Windows approach | Order |
|---|---|---|---|
| Launcher | `apps.d` paths under `/usr/share`, `xdg-open`, systemd status | resolve paths via `task_platform.paths`, `os.startfile` for Files, hide System/systemd cards | 1 |
| Core (task-core) | Unix socket, udev, accounts/PAM-like local auth | named pipe or localhost TCP with token; pyserial/WMI discovery; **largest port** | 3 |
| Mesh (task-mesh) | udev discovery, systemd user service, D-Bus notifications, `paplay` | COM ports via pyserial (meshtastic lib already supports Windows), Qt notifications/audio, background process | 2 |
| Maps & GPS | gpsd | NMEA serial reader backend behind the GPS interface | 2 |
| Radio / APRS | Direwolf (Linux package), BlueZ | Direwolf has Windows builds; KISS over TCP works unchanged. UV-PRO Bluetooth: **unverified on every platform** | 4 |
| SDR Studio | SoapySDR from Debian | SoapySDR/librtlsdr Windows binaries; RTL-SDR Blog V4 needs a V4-capable librtlsdr | 4 |
| Offline Library / Medical | python3-libzim from Debian | python-libzim Windows wheels; Qt WebEngine available on Windows | 1 |
| Devices (console) | task-core socket | follows Core port | 3 |

## Packaging tools evaluated (all open source)

| Tool | License | Output | Fit |
|---|---|---|---|
| **PyInstaller** (onedir) | GPL-2.0 with bootloader exception | folder with `.exe` | Mature PySide6 support; recommended for the first experimental build. |
| Nuitka | Apache-2.0 | compiled `.exe` | Faster startup, much slower builds; evaluate later. |
| cx_Freeze | PSF-style | folder / MSI | Viable alternative. |
| Briefcase (BeeWare) | BSD-3-Clause | MSI via WiX | Opinionated project layout; heavier change. |
| **NSIS** | zlib/libpng | `.exe` installer with uninstaller | Recommended wrapper for per-user install + uninstall. |
| **WiX Toolset** | MS-RL | `.msi` | Recommended when an MSI is needed for managed deployment. |
| Inno Setup | own permissive license (not OSI-approved) | `.exe` installer | Works well, but prefer OSI-licensed tooling. |

Proposed first build: PyInstaller onedir of Launcher + Library + Mesh, wrapped in a
per-user NSIS installer (no admin rights, no auto-start, uninstall keeps user data
unless the user ticks a box). Build in GitHub Actions `windows-latest` and test on a
real Windows 11 x64 machine before any claim.

## Hardware on Windows

* Meshtastic USB: CP210x/CH9102/ESP32-S3 drivers come from Windows Update or the
  vendor; T.A.S.K. will not install drivers.
* RTL-SDR: requires replacing the DVB-T driver with WinUSB (Zadig) — a user action we document, never automate.
* GPS: USB GPS pucks appear as COM ports; T.A.S.K. will read NMEA directly.
* BTECH UV-PRO: its Bluetooth Serial Port service has **not** been verified as KISS on any OS. No support is claimed.

## What is needed to start Milestone E builds

A Windows 11 x64 test machine (or VM with USB pass-through) owned by a tester,
CI on GitHub Actions (after the repository is published), and maintainer approval.
