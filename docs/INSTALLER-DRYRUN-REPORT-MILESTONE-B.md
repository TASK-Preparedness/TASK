# Installer dry-run validation report (task_installer 0.2.0.dev0, Milestone B, 2026-11-22)

**The installer is DRY RUN ONLY.** It has never run on a Raspberry Pi. UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.

## Part 1: simulated hosts (18 fixtures)
Each fixture is a fake root (`/proc/cpuinfo`, device-tree model, `/etc/os-release`, dpkg status and arch).
Every mode was tried on each. Every generated plan passed `plan.assert_safe()`: no purge/autoremove, no
systemctl, no shells, no pip, no rm/dd, no flashing tools, no `--force*`. Manual model selection cannot
override the arch/OS checks (`x86-manual-pi5` is refused). Plans use the real Milestone B bundle, and its
checksums are verified by the installer.

Offline apt steps are guarded: each `apt-get install` of local .debs comes right after a read-only
`apt-get install --print-uris` check, which must list only `file:` URIs. `--no-download` was dropped because
Debian 13's apt 3.0.4 aborts ("Internal Error, Pathname to install is not absolute") when it is combined
with local .deb paths. This was found by Part 2.

| Fixture | Host | Compatible | Profile | Complete | Custom (mesh, maps) | Minimal |
|---|---|---|---|---|---|---|
| `pi5-dev` | Pi 5 8 GB, Debian 13 arm64, T.A.S.K. installed as on the development Pi (modified notifier) | yes | full | update plan, 4 steps, assert_safe OK | update plan, 4 steps, assert_safe OK | update plan, 3 steps, assert_safe OK |
| `pi5-clean` | Pi 5 4 GB, clean Debian 13 arm64 | yes | full | install plan, 3 steps, assert_safe OK | install plan, 3 steps, assert_safe OK | install plan, 3 steps, assert_safe OK |
| `pi4-4gb` | Pi 4 4 GB, Debian 13 arm64 | yes | full | install plan, 3 steps, assert_safe OK | install plan, 3 steps, assert_safe OK | install plan, 3 steps, assert_safe OK |
| `pi4-2gb` | Pi 4 2 GB, Debian 13 arm64 | yes | full | install plan, 3 steps, assert_safe OK | install plan, 3 steps, assert_safe OK | install plan, 3 steps, assert_safe OK |
| `pi4-1gb` | Pi 4 1 GB, Debian 13 arm64 | yes | no-webengine | install plan, 3 steps, assert_safe OK | install plan, 3 steps, assert_safe OK | install plan, 3 steps, assert_safe OK |
| `pi400` | Pi 400, Debian 13 arm64 | yes | full | install plan, 3 steps, assert_safe OK | install plan, 3 steps, assert_safe OK | install plan, 3 steps, assert_safe OK |
| `pi3bplus` | Pi 3 B+ 1 GB, Debian 13 arm64 | yes | no-webengine | install plan, 3 steps, assert_safe OK | install plan, 3 steps, assert_safe OK | install plan, 3 steps, assert_safe OK |
| `zero2w` | Pi Zero 2 W, Debian 13 arm64 | yes | minimal-only | refused (mode not allowed on this board) | refused (mode not allowed on this board) | install plan, 3 steps, assert_safe OK |
| `zero-w` | Pi Zero W (ARMv6) | NO | none | refused (host not compatible) | refused (host not compatible) | refused (host not compatible) |
| `pi5-bookworm` | Pi 5, Debian 12 bookworm arm64 | NO | full | refused (host not compatible) | refused (host not compatible) | refused (host not compatible) |
| `pi4-32bit` | Pi 4, 32-bit userland (armhf) on a 64-bit kernel | NO | full | refused (host not compatible) | refused (host not compatible) | refused (host not compatible) |
| `x86-trixie` | x86_64 PC, Debian 13 amd64 | NO | full | refused (host not compatible) | refused (host not compatible) | refused (host not compatible) |
| `arm64-generic` | Generic arm64 board (no Pi device tree), Debian 13 | yes | full | install plan, 3 steps, assert_safe OK | install plan, 3 steps, assert_safe OK | install plan, 3 steps, assert_safe OK |
| `pi5-manual-pi4` | Pi 5 detected, user manually selects Pi 4 | yes | full | install plan, 3 steps, assert_safe OK | install plan, 3 steps, assert_safe OK | install plan, 3 steps, assert_safe OK |
| `x86-manual-pi5` | x86_64 PC, user manually selects Pi 5 (must not bypass) | NO | full | refused (host not compatible) | refused (host not compatible) | refused (host not compatible) |
| `pi5-revision-mismatch` | Device tree says Pi 5, revision code says Zero 2 W | yes | minimal-only | refused (mode not allowed on this board) | refused (mode not allowed on this board) | install plan, 3 steps, assert_safe OK |
| `pi5-pip-console` | Pi 5 with a legacy pip copy in /usr/local/bin/task-console | yes | full | install plan, 3 steps, assert_safe OK | install plan, 3 steps, assert_safe OK | install plan, 3 steps, assert_safe OK |
| `pi5-newer-installed` | Pi 5 with task-launcher 0.3.9 installed (newer than the bundle) | yes | full | refused by preflight | refused by preflight | refused by preflight |


The full per-fixture details (detected model/revision, warnings, every planned argv for install, repair,
update, uninstall and recovery) are in `DRYRUN-MATRIX.md` and `dryrun-matrix.json`.

## Part 2: inside a Debian 13 arm64 chroot (qemu-user emulation on x86_64)
`packaging/debian/chroot_test.py`, scenario `installer`: the installer's read-only detection and the
Complete plan ran **inside arm64**. The test harness, not the installer, then executed the planned argv
against the bundle. The apt cache was pre-filled with Debian dependencies as a stand-in for the Milestone D
offline bundle.

* PASS installer: detect inside arm64 chroot (real files, read-only)
* PASS installer: Complete plan generated inside arm64 (no Pi model -> warning only)
* PASS installer: dependencies pre-fetched into the apt cache (stand-in for Milestone D)
* PASS installer: planned step 'verify the offline bundle checksums' succeeds
* PASS installer: planned check 'check that nothing would be downloaded (read-only, must list only local files)' passes (only file: URIs)
* PASS installer: planned step 'install T.A.S.K. packages from local files only' succeeds
* PASS installer: all T.A.S.K. packages installed by the planned argv
* PASS installer: no enabled units / autostart / home files

The plan generated in the chroot is in `installer-plan-in-chroot.txt`. Not covered: real Pi detection
(the chroot has no Pi device tree), the GUI wizard on a real display, privilege handling (no executor exists),
and Pi 4/3 hardware.
