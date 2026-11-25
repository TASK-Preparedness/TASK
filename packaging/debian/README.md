# Debian packaging (Milestone B)

**Status: built and tested in an emulated Debian 13 arm64 chroot (qemu-user) on an x86_64 build
machine. NOT validated on Raspberry Pi hardware. UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.**
Debian packages are the supported install path; pip (`console/deploy/install-console.sh`) is developer-only.

## Tools

| File | What it does |
|---|---|
| `build_debs.py OUTDIR [--verify-mesh-031 NOTIFIER] [--verify-console-020]` | Builds all ten packages reproducibly, runs the safety gates and a cross-package file-conflict check, writes `SHA256SUMS`, `BUILD-REPORT.json`, `BUNDLE.json` (read by the installer) and source tarballs. |
| `verify_debs.py BUILD_DIR [--json F]` | Compares each .deb with the delivered .deb (`reference/delivered-debs.sha256`) and every payload file with the files installed on the development Pi (`reference/pi-installed-usr-20261108.sha256`, collected 2026-11-08). |
| `chroot_test.py` (root, build machine only) | Debian 13 arm64 chroot scenarios: each package alone (install → import smoke → remove → purge → leftover check), all together with Recommends, upgrade from the Pi's installed versions with its modified notifier and rollback, the installer's plan executed inside arm64, and the commands of docs/VOLUNTEER-TESTING.md. |
| `check_baseline.py BUILD_DIR` | Checks the debs' relations against the Pi's reported package versions. |
| `reference/` | Control files and checksums of the delivered debs, and `/usr` checksums of the Pi installation. |

All packages are pure Python: **`Architecture: all`**. "arm64" here means "dependencies resolve and
the code imports on Debian 13 arm64", nothing more. Nothing in this directory touches a Raspberry Pi.

## Chroot results (2026-11-22, Debian 13 arm64 under qemu-user, apt 3.0.4)

* **each** (every package alone: install with Depends from Debian arm64, import smoke, policy, remove,
  purge, leftovers): 50/50 checks passed (after a harness fix: dependencies are installed before the
  leftover snapshot).
* **all** (all ten with Recommends; dpkg --verify; apt-get check; arm64 byte-compile of every .py;
  imports; units present and not enabled; py3compile/py3clean; remove; purge): all passed.
* **upgrade** (delivered set + the Pi's modified notifier + simulated `/etc/task/core.toml` → Milestone B set,
  offline): all passed. The notifier keeps the Pi's sha256 2864d242…; `dpkg --verify` is clean afterwards;
  site config is untouched after upgrade and after remove.
* **installer**: the planned argv installs everything. See docs/INSTALLER-DRYRUN-REPORT-MILESTONE-B.md.
* Findings: task-console 0.2.0 lacked `python3-pyside6.qtnetwork`; `apt-get --no-download` fails with
  local .debs in apt 3.0.4.

## Reproducibility

* `SOURCE_DATE_EPOCH` per package: 1791792000 = 2026-10-12 08:00 UTC (Phase 4C/4F/4G builds),
  1791633600 = 2026-10-10 12:00 UTC (resources), and 1795476600 = 2026-11-23 18:30 -0500 (the approved alpha
  versions: launcher 0.3.8, console 0.2.1~alpha1, mesh 0.3.2~alpha1). Also `--root-owner-group`, sorted md5sums,
  xz and `gzip -9n`. Every path, including the package root, is set to the epoch, so the build date never leaks.
* Two independent builds give identical `SHA256SUMS`.
* The seven packages whose version is unchanged are **byte-identical** to the delivered/Pi-installed .debs.
  Verification builds (`--verify-mesh-031 --verify-console-020 --verify-launcher-037`) of the Pi's
  task-mesh 0.3.1, task-console 0.2.0 and task-launcher 0.3.7 are byte-identical too, built from the
  Milestone A commit for the launcher.

## Versions (volunteer test round 1, 2026-11-23)

| Package | Version | On the Pi | Note |
|---|---|---|---|
| python3-task-comms | 0.3.1 | 0.3.1 | byte-identical |
| task-core | 0.3.0 | 0.3.0 | byte-identical; system unit shipped, never enabled |
| task-core-compat | 0.3.0 | 0.3.0 | byte-identical |
| task-console | **0.2.1~alpha1** | 0.2.0 | adds `python3-pyside6.qtnetwork`; payload = Pi except changelog |
| task-aprs | 0.1.0 | 0.1.0 | byte-identical |
| task-sdr | 0.2.4 | 0.2.4 | byte-identical |
| task-mesh | **0.3.2~alpha1** | 0.3.1 + hand-modified notifier | ships the Pi's notifier (sha256 2864d242…) as maintained source; Recommends pulseaudio-utils, Suggests ffmpeg + sound-theme-freedesktop; payload = Pi except changelog; user unit shipped, never enabled |
| task-launcher | **0.3.8** | 0.3.7 | Windows portability changes merged; Devices tile prefers `/usr/bin/task-console`; payload = Pi except 7 changed files + changelog |
| task-maps | 0.1.1 | 0.1.1 | byte-identical |
| task-resources | 0.2.4 | 0.2.4 | byte-identical |

The three bold versions were **approved on 2026-11-23 for packaging, building and isolated testing only**
(not for the working Pi, not for publication). `~alpha1` sorts below the final version, so later releases upgrade cleanly.

### Dependency bug found (task-console 0.2.0)
`task_console/core_client.py` imports `PySide6.QtNetwork`, but 0.2.0 depends only on qtcore, qtgui and qtwidgets.
In the arm64 chroot, task-console installed alone fails to import. On the Pi it works only because
task-launcher depends on `python3-pyside6.qtnetwork`. 0.2.1~alpha1 adds the dependency; there is no code change.
A static import-vs-Depends scan of all ten packages found no other missing dependency.

## Dependencies vs. the development Pi's baseline (2026-11-22)

`check_baseline.py BUILD_DIR` checks every Depends/Recommends/Suggests relation against
`reference/pi-dpkg-baseline-20261122.txt`. That file holds the dpkg versions Joshua reported from the Pi:
python3 3.13.5-1, PySide6 6.8.2.1-4, numpy, scipy, serial, protobuf, pubsub, pyudev, libzim, yaml, gpsd,
direwolf, ffmpeg, pulseaudio-utils, librtlsdr0 and SoapySDR. It also records that librtlsdr2 and
soapysdr-module-all are **not** installed.

* **0 Depends violations.** Every version floor (`python3 (>= 3.11|3.13)`, `python3-pyside6.* (>= 6.8)`,
  `python3-serial (>= 3.5)`, `python3-pubsub (>= 4.0.3)`, `python3-protobuf (>= 3.21.12)`, `python3-pyudev (>= 0.24.3)`,
  `python3-libzim (>= 3.6)`, `python3-yaml (>= 6)`, `librtlsdr0 (>= 2.0.2)`) is met by the Pi's versions.
  No floor was raised: floors state the minimum the code needs, not the Pi's exact versions.
* task-sdr needs `librtlsdr0` (present). It does not use librtlsdr2, and SoapySDR is optional (Suggests).
* Depends not in the reported baseline: python3-requests, -tabulate, -packaging, -pycryptodome (>= 3.20),
  -jeepney (>= 0.8) and qt6-wayland (task-mesh), and ca-certificates (task-resources). They must be present on
  the Pi, because dpkg reports task-mesh 0.3.1 and task-resources 0.2.4 as "install ok installed" with the
  **same** Depends. Their exact versions are not recorded (low priority).
* Recommends not in the baseline (fonts-inter, qt6-wayland, qt6-svg-plugins, xdg-utils, qt6-qpa-plugins,
  fonts-dejavu-core) are optional.

The chroot's resolved versions (`resolved-packages-arm64.txt`) are what Debian 13 arm64 provides today, not the Pi's.

## Safety rules enforced at build time (`gate()`; the build fails on any)

* Maintainer scripts: no `systemctl`, `deb-systemd-*`, `apt`/`apt-get`/autoremove, user/group changes,
  `update-rc.d`/`invoke-rc.d`, `rfkill`, `bluetoothctl`. Only task-mesh has scripts: `py3compile` on
  configure and `py3clean` on removal of its private tree.
* No autostart entries, presets, `.wants/` symlinks, `/etc/systemd`, `/home` or `/root` paths.
* Unit files are byte-identical to the units installed on the Pi.
* Every `/etc` file must be a conffile. No package ships `/etc` files today, so site configuration
  (e.g. `/etc/task/*.toml` written by `task-core-migrate`) is never touched by install, upgrade or remove;
  the upgrade scenario checks this.
* No private patterns (`/home/<user>`, user@host, MAC-address shapes outside vendored upstream wheels),
  no `.pyc`, WAV, SQLite, MBTiles or ZIM files.
* No two packages ship the same file. task-mesh keeps `Provides/Replaces/Breaks: rain-mesh`; the other
  packages use new names and paths, so they do not overlap with the R.A.I.N. packages they replace.

## lintian (2.122.0, Debian 13)

Not fixed on purpose: fixing them would change released bytes and maintainer data that needs approval.
* errors: `bogus-mail-host-in-debian-changelog` / `malformed-contact`: placeholder maintainer `TBD-maintainer-email`. The 2026-11-23 volunteer-test packages keep this placeholder so their SHA-256 checksums stay unchanged; user-facing contact is GitHub Issues and private vulnerability reporting, not this field.
* warnings: `extended-description-line-too-long`, `no-manual-page`, `debian-changelog-line-too-long`,
  `appstream-metadata-validation-failed` (task-mesh metainfo).

## Placeholders reported to the licence audit (not changed here)

* `Maintainer: T.A.S.K. Development Team <TBD-maintainer-email>` in every package.
* Shipped `copyright` files: `Source: T.A.S.K. (Tactical Access Support Kit) — upstream URL TBD`
  (comms, core, compat, console, aprs, sdr, mesh); `Source: R.A.I.N. project (rain-core repository, directory …/)`
  (launcher, maps, resources: outdated project name, no URL).
* `mesh/packaging/debian/copyright` (source tree only, not used by the builder): `Source: https://example.invalid/task-mesh`
  and the "T.A.S.K. Mesh Operations contributors" holder (approval #2).
