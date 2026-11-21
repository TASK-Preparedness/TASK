# Raspberry Pi installer architecture

Code: `installers/raspberry-pi/task_installer/` (0.1.0.dev0, **dry run only**).
UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.

```
detect.py  ──►  compat.py  ──►  catalog.py  ──►  plan.py  ──►  executor.py
(read-only      (matrix +        (modules,         (install/        (DryRun now;
 facts)          hard gates)      maturity, deps)   repair/update/   real executor
                                                     uninstall)       after Milestone B)
        front ends:  tui.py (text, headless)   gui.py (PySide6 QWizard)
```

## Detection (read-only)
Board model from `/proc/device-tree/model`; userland arch via `dpkg --print-architecture`
(kernel `uname -m` reported too — a 64-bit kernel with a 32-bit userland is rejected);
OS from `/etc/os-release`; RAM from `/proc/meminfo`; free disk via `statvfs`; desktop
from `XDG_CURRENT_DESKTOP`/`DISPLAY`/`WAYLAND_DISPLAY`; USB devices from
`/sys/bus/usb/devices/*/idVendor|idProduct` (recognises CP210x/CH9102/CH340/ESP32-S3
bridges as *possible* mesh nodes, RTL-SDRs, u-blox GPS); Bluetooth adapters listed from
`/sys/class/bluetooth` without scanning; installed packages from `/var/lib/dpkg/status`.
Nothing opens `/dev` nodes, so no ESP32 is reset and no device ownership changes. A test
asserts no `/dev/` path is opened.

## Compatibility gate
Hard requirements (always from detected facts): arm64 userland, Debian 13 trixie
(or Raspberry Pi OS based on it), enough disk. Model matrix decides the module
profile: `full` (Pi 5/4/400/500/CM4/CM5), `no-webengine` (Pi 3/CM3), `minimal-only`
(Zero 2 W), unsupported (Pi 1/2/Zero). A manual model choice is honoured only when it
is **stricter** than the detected board; it can never override arch/OS checks.

## Modes
* **Complete** — every installable (tested/experimental) module allowed by the profile.
* **Custom** — user's choice + automatically added shared dependencies (e.g. Mesh → comms).
* **Minimal** — Core + Launcher.
Planned/unavailable modules are listed but cannot be selected. Each module shows version,
maturity, packages, notable dependencies, hardware and an installed-size estimate.

## Plans and safety
Plans are argv lists; `assert_safe` rejects `purge`, `autoremove`, `systemctl`, `enable`,
`restart`, shells and flashing tools. Offline installs use local `.deb`s with
`--no-download`. Uninstall = `apt-get remove` (keeps `/etc/task` conffiles and all
home-folder data). Update records versions first for rollback. Repair starts with
`dpkg --verify` and warns that re-installing overwrites intentional local edits.

## Privilege model
The GUI refuses to run as root. In a future real executor, privileged steps run via
`sudo` in a terminal (or a minimal polkit helper, if approved) — never a root GUI.

## First launch
No service is enabled and nothing autostarts. The finish page tells the user how to open
the launcher; Mesh service, audible alert and radio transmit stay opt-in.

## Relationship to `release/common`
`release/common/{preflight,install,rollback,task-guard}.sh` is the existing hardened
per-release installer (host hard-requirement, fake-apt tests). The new installer reuses
its rules (arm64 + trixie, no purge/autoremove/systemctl) and will call the same apt
patterns once packages are validated.
