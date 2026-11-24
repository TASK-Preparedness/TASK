# Installing T.A.S.K. (experimental alpha)

> **EXPERIMENTAL ALPHA — NOT VALIDATED ON A PHYSICAL RASPBERRY PI.**
>
> These steps are for volunteer testers. The packages have been built and
> exercised in an emulated Debian 13 arm64 chroot on an x86_64 machine. They
> have **not** been installed or accepted on a clean physical Raspberry Pi.
> Use a **spare SD card**. Do not install this on a production system or on a
> Pi you cannot afford to rebuild. Back up any data you care about first.
>
> The graphical and text installer in this tree is a **dry run only**. It can
> inspect your board and show a plan; it will not install, upgrade, or remove
> packages. Volunteer installs use `dpkg`/`apt` by hand.

For **volunteer test round 1** (install, start, and removal on a spare
card, no radios attached), follow [docs/VOLUNTEER-TESTING.md](docs/VOLUNTEER-TESTING.md)
first. That guide's commands are the ones exercised in the emulated arm64
chroot. This page is the longer reference: requirements, SHA-256 checks,
the dry-run installer, one-package-at-a-time installs, uninstall and
rollback.

Read [SAFETY.md](SAFETY.md) and [KNOWN-ISSUES.md](KNOWN-ISSUES.md) before you
begin. Windows is not supported; see [WINDOWS.md](WINDOWS.md).

**Run one command at a time.** Paste a block, wait until it finishes, then
paste the next. Do not chain these with `&&` until you are comfortable with
each step.

## Requirements

* A **Raspberry Pi 5** (this alpha's only requested test board).
* **Debian 13 "trixie" arm64** or Raspberry Pi OS 64-bit based on trixie, with
  a desktop session.
* A **spare SD card** (recommended) and a way to flash a clean OS image onto it.
* About 300 MB free space plus room for any maps, ZIM files, or libraries you
  add yourself.
* The release assets and their `SHA256SUMS` file from the GitHub Release (or
  the review bundle you were given).

This alpha is **not** a supported install path for Pi 4/400/3, Zero 2 W,
32-bit OS images, Debian 12, or Windows.

## 0. Back up and prepare a spare card

If the Pi already has data you care about, copy it off the card first (for
example `~/.config/task-*`, `~/.local/share/task-*`, `/etc/task`, maps, and
ZIM libraries). Then flash a clean Debian 13 / Raspberry Pi OS 64-bit trixie
image onto a **spare** card and boot from that card.

Log in as your normal user (not root) on the desktop.

## 1. Confirm the board and OS

Paste this by itself, then send the output with your test report if you
open one:

```
cat /proc/device-tree/model; echo; grep Revision /proc/cpuinfo; dpkg --print-architecture; cat /etc/os-release
```

You want a Raspberry Pi 5, architecture `arm64`, and Debian / Raspberry Pi OS
13 (trixie). If the architecture is not `arm64`, or the OS is not 13/trixie,
stop. This alpha is not for that system.

## 2. Download the packages and verify SHA-256

Download the experimental arm64 package archive (or the individual `.deb`
files) and the `SHA256SUMS` file from the same GitHub Release into one
directory. For volunteer test round 1 the package archive is
`TASK-volunteer-test-debs-20261123.zip`, built from `milestone-b` commit
`902ba33`. Its SHA-256 is:

```
ba50f7de2e599023e60f0c186a9de144a708ffd6ff83c88a61ee0f508a0fbf4e  TASK-volunteer-test-debs-20261123.zip
```

Then, in the directory that holds the zip (and after unpacking, in the
directory that holds the `.deb` files and their own `SHA256SUMS`), run:

```
sha256sum -c SHA256SUMS
```

Every listed file must print `OK`. If any file fails, **do not install it**.
Download again, or stop and file an installation-problem issue.

If you only have a single archive, you can also check it by itself:

```
sha256sum TASK-*.zip TASK-*.tar.gz TASK-*.deb
```

Compare the printed hashes to the published `SHA256SUMS` by eye if
`sha256sum -c` is not available.

The individual packages in that volunteer-test build, each **experimental**
and **NOT validated on a physical Raspberry Pi**, are:

| Package file | Version | SHA-256 |
|---|---|---|
| `python3-task-comms_0.3.1_all.deb` | 0.3.1 | `8956231817cbfe2dd0f285fe5b84b5df4abd408c8e00af40f3a5996d6e4b09e4` |
| `task-core_0.3.0_all.deb` | 0.3.0 | `a48197329d50197f62cf8b4db87963b4d57c275ba587a2ae5a1b12627385f5e1` |
| `task-core-compat_0.3.0_all.deb` | 0.3.0 | `3ec1bbfb4b63e55fe73d236d76b8cc2d561c32d8a0883327f718a1486df95da0` |
| `task-console_0.2.1~alpha1_all.deb` | 0.2.1~alpha1 | `a150b01d34733d1de6b124ae1827238c07a680db75b312209ae428f84a77ddfd` |
| `task-aprs_0.1.0_all.deb` | 0.1.0 | `640604311eaf3a60e1992a2d3a3459149191a9aee1b621d001a9cb2f05c3a283` |
| `task-sdr_0.2.4_all.deb` | 0.2.4 | `5bcec72059da184e2a6e53d18f21d2d504a9c143a5234cec86f4801493236a82` |
| `task-mesh_0.3.2~alpha1_all.deb` | 0.3.2~alpha1 | `1f3bd20de4152e01d8cc2c96bd5a045914b2f152413b832fa62356cc78319e76` |
| `task-launcher_0.3.8_all.deb` | 0.3.8 | `a8771804ba7d99fc7d2cb78a0ee99a989a343381ff6436c7f43865e223a5e440` |
| `task-maps_0.1.1_all.deb` | 0.1.1 | `e45652d283c2b9abb94113b618073784beb3a4200e58e2bcaf268e0a512d5b0d` |
| `task-resources_0.2.4_all.deb` | 0.2.4 | `064aa332db0de2e52e82891f4ab295972331758e91e269ddd32aa6b90cd457e5` |

## 3. Optional: run the installer in dry-run mode (safe)

This does not install anything. From an unpacked source tree, or a clone of
this repository:

```
cd installers/raspberry-pi
```

Then, separately:

```
/usr/bin/python3 -m task_installer detect
```

The detect command only reads hardware and OS information. You may also try
the text or graphical dry-run wizard (`tui` or `gui`). Those will print or
show the commands they *would* run; they will not run them.

## 4. Install Debian dependencies, then the T.A.S.K. packages

The T.A.S.K. `.deb` files are `Architecture: all`. They need Debian 13 arm64
libraries such as Python 3.13, PySide6 6.8, and (depending on the modules you
install) numpy, scipy, libzim, SoapySDR/librtlsdr0, gpsd, and Direwolf.

A Complete-style install uses these packages, or the subset you actually want.
Every package below is **experimental** and **NOT validated on a physical Raspberry Pi**:

| Package | Intended version in this alpha |
|---|---|
| `task-core` | 0.3.0 |
| `task-core-compat` | 0.3.0 (optional; R.A.I.N. command compatibility) |
| `python3-task-comms` | 0.3.1 |
| `task-launcher` | 0.3.8 |
| `task-mesh` | 0.3.2~alpha1 |
| `task-maps` | 0.1.1 |
| `task-aprs` | 0.1.0 |
| `task-sdr` | 0.2.4 |
| `task-resources` | 0.2.4 |
| `task-console` | 0.2.1~alpha1 |

Exact filenames are in `SHA256SUMS`. If [docs/VOLUNTEER-TESTING.md](docs/VOLUNTEER-TESTING.md) is present in your tree or bundle, prefer its exact package commands; the order below matches that guide's intended sequence. Versions with `~alpha1` are experimental
pre-releases.

Install **dependencies from Debian first** (one command). This uses your
normal apt sources; a fully offline bundle is not part of this alpha (see
[OFFLINE.md](OFFLINE.md)):

```
sudo apt update
```

Then, separately (you can drop packages for modules you are not testing):

```
sudo apt install python3 python3-yaml python3-pyudev python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets python3-pyside6.qtnetwork python3-pyside6.qtsvg python3-pyside6.qtdbus python3-pyside6.qtmultimedia python3-pyside6.qtwebenginewidgets python3-serial python3-pubsub python3-protobuf python3-requests python3-tabulate python3-packaging python3-pycryptodome python3-jeepney python3-numpy python3-scipy python3-libzim python3-pyudev librtlsdr0 qt6-wayland fonts-inter fonts-dejavu-core xdg-utils gpsd direwolf ca-certificates
```

If apt cannot find a package, stop and report it; do not force half-installed
sets.

Then install the T.A.S.K. packages from the verified files, in this order,
one command at a time, from the directory that holds the `.deb` files:

```
sudo apt install ./python3-task-comms_0.3.1_all.deb
```

```
sudo apt install ./task-core_0.3.0_all.deb
```

```
sudo apt install ./task-core-compat_0.3.0_all.deb
```

```
sudo apt install ./task-launcher_0.3.8_all.deb
```

```
sudo apt install ./task-console_0.2.1~alpha1_all.deb
```

```
sudo apt install ./task-mesh_0.3.2~alpha1_all.deb
```

```
sudo apt install ./task-maps_0.1.1_all.deb
```

```
sudo apt install ./task-aprs_0.1.0_all.deb
```

```
sudo apt install ./task-sdr_0.2.4_all.deb
```

```
sudo apt install ./task-resources_0.2.4_all.deb
```

If a filename in your bundle differs (for example a rebuild suffix), use the
name printed in `SHA256SUMS`. `apt install ./file.deb` is preferred over
raw `dpkg -i` because apt can still pull missing Depends.

These packages do **not** enable or start systemd services. They do **not**
flash firmware. They do **not** overwrite `/etc/task`, your home directory,
maps, or ZIM libraries.

`task-mesh` 0.3.2~alpha1 **Recommends** `pulseaudio-utils` (for `paplay`).
A networked `apt install` of these packages will usually offer to install
it if it is missing. For a fully offline upgrade on a system that does
not already have `pulseaudio-utils`, apt may try to download it unless
you use `--no-install-recommends` or provide the package locally. The
development Pi already has `pulseaudio-utils` 17.0+dfsg1-2+rpt1. See
[KNOWN-ISSUES.md](KNOWN-ISSUES.md).

## 5. Confirm what was installed

```
dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\n' 'task-*' python3-task-comms
```

Keep this output for your test report.

You can start the launcher (from a desktop session) with:

```
task-launcher
```

Nothing should start automatically at boot.

## Updating

Keep the previous `.deb` files and the previous `SHA256SUMS`. To update later,
verify the new files, then `sudo apt install ./package_newversion_all.deb`
for each package you are updating, one at a time. Configuration under
`/etc/task` and `~/.config/task-*`, and data under `~/.local/share/task-*`,
should be left in place. Do not run `apt dist-upgrade` or `apt-get dist-upgrade` just to update
T.A.S.K.

## Uninstalling

This removes T.A.S.K. packages but keeps your settings and data. **Do not**
use `apt-get purge` or `apt-get autoremove` for this (those can delete
configuration or shared libraries you still want).

```
sudo apt-get remove task-launcher task-mesh task-maps task-aprs task-sdr task-resources task-console task-core-compat python3-task-comms task-core
```

Shared Debian packages such as Qt, Direwolf, gpsd, and SoapySDR stay
installed. Your settings (`/etc/task`, `~/.config/task-*`), data
(`~/.local/share/task-*`), maps, ZIM libraries, and message history are
kept.

## Rollback

If a new package misbehaves and you still have the previous verified `.deb`
files:

```
sudo apt-get install ./task-example_previousversion_all.deb
```

Run that once per package you need to roll back, using the older verified
files. If the system is not bootable or the desktop is unusable, take the
spare card out and return to your previous card. That is the main reason this
alpha should be tested on a spare card.

## Running tests (optional, for developers)

See [TESTING.md](TESTING.md). On a test Pi you may run
`scripts/run-all-tests.sh` if you have installed the Debian test packages
listed in [CONTRIBUTING.md](CONTRIBUTING.md). Failures on hardware are useful;
please file a test report either way.

## Reporting problems

See [SUPPORT.md](SUPPORT.md). Please include the board/OS output from step 1,
the package versions from step 5, and redacted logs.
