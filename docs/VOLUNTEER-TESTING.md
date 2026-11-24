# T.A.S.K. volunteer test — round 1 (alpha, 2026-11-23)

> **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.** These are **experimental alpha** packages.
> They are **NOT validated on a physical Raspberry Pi.** So far they have only been tested in an
> **emulated** Debian 13 arm64 environment on a PC, never on a real Raspberry Pi. You are the
> first real-hardware test. Expect problems.
>
> * **No RF transmission.** Do not connect any radio, Meshtastic node, SDR or GPS for this round,
>   and do not enable any transmit setting. This round tests install, start and removal only.
> * **No Windows support** is claimed or provided. This test is for Raspberry Pi only.
> * These packages are not published and not an official release. Please don't share them further.
> * License: Option A (GNU GPL plus a separate T.A.S.K. trademark policy) has been selected,
>   pending final review of the legal documents. The packages keep their existing notices
>   until those documents are approved and substituted.

## Who should test

Test only if **all** of these are true:

* You have a **Raspberry Pi 5**. Other models are not part of this round.
* It runs **Debian 13 "trixie", 64-bit (arm64)**. Plain Debian or Raspberry Pi OS based on trixie, 64-bit, is fine.
* It uses a **spare SD card or a non-production system** that you can wipe afterwards. Never test on a
  Pi you depend on.
* T.A.S.K. or R.A.I.N. has **never** been installed on it. If it has, use a fresh card instead.
* It has internet access. apt downloads the Debian dependencies, which include Qt and are several hundred MB.

Check your system. Run each command and compare with the expected output:

```
cat /proc/device-tree/model; echo
```
Expected: `Raspberry Pi 5 Model B Rev …`

```
dpkg --print-architecture
```
Expected: `arm64`

```
grep VERSION_CODENAME /etc/os-release
```
Expected: `VERSION_CODENAME=trixie`

```
dpkg -l 'task-*' 'rain-*' 2>/dev/null | grep '^ii'
```
Expected: **no output**. If anything is listed, stop and use a fresh card.

## 1. Check the download

You receive `TASK-volunteer-test-debs-20261123.zip` and its SHA-256 value from the maintainer
(or from the published `SHA256SUMS` file). The expected SHA-256 of that zip, from the
2026-11-23 volunteer-test build, is:

```
ba50f7de2e599023e60f0c186a9de144a708ffd6ff83c88a61ee0f508a0fbf4e  TASK-volunteer-test-debs-20261123.zip
```

Put the zip in your home folder, then run:

```
cd ~
```
```
sha256sum TASK-volunteer-test-debs-20261123.zip
```
The 64-character value must match the one above **exactly**. If it does not, stop and report it.

```
unzip TASK-volunteer-test-debs-20261123.zip
```
```
cd task-volunteer-test
```
```
sha256sum -c SHA256SUMS
```
Expected: ten lines ending in `OK` and no `FAILED`. Those ten files and SHA-256
values, from the 2026-11-23 volunteer-test build (all **experimental** and **NOT
validated on a physical Raspberry Pi**), are:

```
8956231817cbfe2dd0f285fe5b84b5df4abd408c8e00af40f3a5996d6e4b09e4  python3-task-comms_0.3.1_all.deb
a48197329d50197f62cf8b4db87963b4d57c275ba587a2ae5a1b12627385f5e1  task-core_0.3.0_all.deb
3ec1bbfb4b63e55fe73d236d76b8cc2d561c32d8a0883327f718a1486df95da0  task-core-compat_0.3.0_all.deb
a150b01d34733d1de6b124ae1827238c07a680db75b312209ae428f84a77ddfd  task-console_0.2.1~alpha1_all.deb
640604311eaf3a60e1992a2d3a3459149191a9aee1b621d001a9cb2f05c3a283  task-aprs_0.1.0_all.deb
5bcec72059da184e2a6e53d18f21d2d504a9c143a5234cec86f4801493236a82  task-sdr_0.2.4_all.deb
1f3bd20de4152e01d8cc2c96bd5a045914b2f152413b832fa62356cc78319e76  task-mesh_0.3.2~alpha1_all.deb
a8771804ba7d99fc7d2cb78a0ee99a989a343381ff6436c7f43865e223a5e440  task-launcher_0.3.8_all.deb
e45652d283c2b9abb94113b618073784beb3a4200e58e2bcaf268e0a512d5b0d  task-maps_0.1.1_all.deb
064aa332db0de2e52e82891f4ab295972331758e91e269ddd32aa6b90cd457e5  task-resources_0.2.4_all.deb
```

## 2. Install

```
sudo apt update
```
Then this **one** command, all on one line:
```
sudo apt install ./python3-task-comms_0.3.1_all.deb ./task-core_0.3.0_all.deb ./task-core-compat_0.3.0_all.deb ./task-launcher_0.3.8_all.deb ./task-console_0.2.1~alpha1_all.deb ./task-mesh_0.3.2~alpha1_all.deb ./task-maps_0.1.1_all.deb ./task-aprs_0.1.0_all.deb ./task-sdr_0.2.4_all.deb ./task-resources_0.2.4_all.deb
```
apt lists what it will install and asks `Do you want to continue? [Y/n]`. Answer `Y`.
**Copy the full output of this command into your report**, especially any lines starting with `E:` or `W:`.

## 3. Check the installation

```
dpkg-query -W -f='${Package} ${Version} ${db:Status-Abbrev}\n' python3-task-comms task-core task-core-compat task-launcher task-console task-mesh task-maps task-aprs task-sdr task-resources
```
Expected: ten lines, each ending in `ii`, with these versions: python3-task-comms 0.3.1, task-core 0.3.0,
task-core-compat 0.3.0, task-launcher 0.3.8, task-console 0.2.1~alpha1, task-mesh 0.3.2~alpha1,
task-maps 0.1.1, task-aprs 0.1.0, task-sdr 0.2.4, task-resources 0.2.4.

```
sudo dpkg --verify python3-task-comms task-core task-core-compat task-launcher task-console task-mesh task-maps task-aprs task-sdr task-resources
```
Expected: **no output**.

```
task-launcher --version
```
Expected: `task-launcher 0.3.8`

```
systemctl is-enabled task-core.service
```
Expected: `disabled`.

```
systemctl --user is-enabled task-mesh-service.service
```
Expected: `disabled`. T.A.S.K. never enables services by itself; please don't enable them for this round.

## 4. Try it (no hardware attached)

Open **T.A.S.K. Launcher** from the desktop menu (or run `task-launcher` in a terminal, as your normal
user, not with sudo). Please note for each step whether it works:

1. The launcher window opens. It may show that task-core is not connected; that is expected.
2. Open the **Devices** tile. It should start T.A.S.K. Console from `/usr/bin/task-console`.
3. Open **Mesh**, **Maps**, **Radio/APRS**, **SDR Studio** and **Library/Medical** one at a time. With no
   hardware attached, they should open and say that no device or content is present. Do not connect
   devices or change transmit settings.
4. Close everything. Log out and back in once, then check that nothing T.A.S.K.-related started by itself.

## 5. What to report

Send this to the maintainer:

```
Pi model (cat /proc/device-tree/model):
RAM size:
OS (cat /etc/os-release | head -3) and (cat /etc/debian_version):
Raspberry Pi OS or plain Debian:
Desktop (Wayland/labwc, X11, other):
Zip SHA-256 matched (yes/no):
sha256sum -c SHA256SUMS all OK (yes/no):
apt install output (paste all of it):
dpkg-query output (paste):
dpkg --verify output (paste; empty is good):
task-launcher --version output:
Step 4 results (1-4, works / problem + what you saw):
Anything that started on its own after re-login:
Uninstall result (section 6):
Screenshots of any error windows:
```
If something crashed, also attach the output of `journalctl --user -b --no-pager | tail -n 200`.
**Before sending, remove anything private from it** (Wi-Fi names, user names, callsigns).

## 6. Uninstall (rollback)

These steps return the card to how it was before step 2. Configuration in `/etc` and your home folder is kept.

```
sudo apt remove python3-task-comms task-core task-core-compat task-launcher task-console task-mesh task-maps task-aprs task-sdr task-resources
```
Check that they are gone:
```
dpkg -l 'task-*' python3-task-comms | grep '^ii'
```
Expected: no output.

Optional, to also delete the packages' own configuration records:
```
sudo apt purge python3-task-comms task-core task-core-compat task-launcher task-console task-mesh task-maps task-aprs task-sdr task-resources
```
Optional, to delete your own T.A.S.K. settings and data, check first and delete only if you are sure:
```
ls -d ~/.config/task-* ~/.local/share/task-* ~/.local/state/task-* 2>/dev/null
```
The Debian packages that apt installed as dependencies (Qt, numpy, …) stay installed. They do no harm.
Re-flash the card if you want a completely clean system.

## Known limitation: pulseaudio-utils

`task-mesh` 0.3.2~alpha1 **Recommends** `pulseaudio-utils` (for `paplay`, used
by the audible mesh alert). On a system that does not already have it, a
normal `apt install` of these packages will offer to install it (several
hundred kilobytes, plus `libpulsedsp`). That is expected. If you are
installing or upgrading fully offline and `pulseaudio-utils` is not already
present, apt may try to download it unless you pass
`--no-install-recommends` or include `pulseaudio-utils` in a local bundle.
The development Pi already has `pulseaudio-utils` 17.0+dfsg1-2+rpt1. Audible
alerts were not exercised in the emulated chroot.

## What has been tested before you (and what has not)

* Tested **in an emulated arm64 chroot** (qemu on a PC, Debian 13): sections 1, 2, 3 and 6 of this guide,
  run with `apt install -y`, plus importing every module without a display. Results are in the volunteer-test package.
* **Not** tested anywhere: a real Raspberry Pi, a real desktop session, sections 4 and 5, any hardware, Pi 4 or other models.
