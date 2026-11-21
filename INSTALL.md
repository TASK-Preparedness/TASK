# Installing T.A.S.K.

> **Pre-release.** There is no published release yet. This page describes what
> exists today and how installation will work. Nothing below changes your
> system unless you run the commands yourself.

## Requirements

* Raspberry Pi 5 (verified) or Pi 4/400 (untested) — see [HARDWARE.md](HARDWARE.md).
* **Debian 13 "trixie" arm64** or Raspberry Pi OS (64-bit) based on trixie, with a desktop.
* About 300 MB free space plus room for your own maps and libraries.

## 1. Check your system with the installer (safe, dry run)

The installer only reads your hardware and shows what it would do.

```bash
git clone https://github.com/TASK-Preparedness/TASK.git   # or unzip TASK-Public-Alpha-Source.zip
cd TASK/installers/raspberry-pi
/usr/bin/python3 -m task_installer detect          # hardware/OS report
/usr/bin/python3 -m task_installer tui             # interactive text installer (dry run)
/usr/bin/python3 -m task_installer gui             # graphical wizard (needs python3-pyside6.qtwidgets)
```

Run these as your normal user. The graphical installer refuses to run as root.
Installation modes: **Complete** (all compatible released modules),
**Custom** (pick modules; shared dependencies are added automatically) and
**Minimal** (launcher + core). Planned modules are shown but cannot be selected.
Repair, update and uninstall plans are offered when T.A.S.K. packages are found.

## 2. Install packages (when a release exists)

Validated arm64 `.deb` packages will be attached to GitHub Releases. Until then,
developers can build them (see CONTRIBUTING.md); built-but-unvalidated packages
must not be described as tested.

## 3. Updating

The installer's *update* plan upgrades only T.A.S.K. packages, keeps configuration
files and never touches your home folder. Keep the previous bundle to roll back.

## 4. Uninstalling

The *uninstall* plan runs `apt-get remove` (never `purge`, never `autoremove`).
Your settings (`/etc/task`, `~/.config/task-*`), data (`~/.local/share/task-*`),
maps, ZIM libraries and message history are kept. Shared packages such as Qt,
Direwolf, gpsd and SoapySDR stay installed.

## Running tests

See [TESTING.md](TESTING.md).
