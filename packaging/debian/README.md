# Debian packaging (Milestone B)

**Status: built and tested in an emulated Debian 13 arm64 chroot (qemu-user) on an x86_64 build
machine. NOT validated on Raspberry Pi hardware. UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.**
Debian packages are the supported install path; pip (`console/deploy/install-console.sh`) is developer-only.

## Tools

| File | What it does |
|---|---|
| `build_debs.py OUTDIR [--verify-mesh-031 NOTIFIER] [--verify-console-020]` | Builds all ten packages reproducibly, runs the safety gates and a cross-package file-conflict check, writes `SHA256SUMS`, `BUILD-REPORT.json`, `BUNDLE.json` (read by the installer) and source tarballs. |
| `verify_debs.py BUILD_DIR [--json F]` | Compares each .deb with the delivered .deb (`reference/delivered-debs.sha256`) and every payload file with the files installed on the development Pi (`reference/pi-installed-usr-20261108.sha256`, collected 2026-11-08). |
| `chroot_test.py` (root, build machine only) | Debian 13 arm64 chroot scenarios: each package alone (install → import smoke → remove → purge → leftover check), all together with Recommends, upgrade from the delivered set with the Pi's modified notifier, and the installer's plan executed inside arm64. |
| `reference/` | Control files and checksums of the delivered debs, and `/usr` checksums of the Pi installation. |

All packages are pure Python: **`Architecture: all`**. "arm64" here means "dependencies resolve and
the code imports on Debian 13 arm64", nothing more. Nothing in this directory touches a Raspberry Pi.

## Reproducibility

* `SOURCE_DATE_EPOCH` per package (1791792000 = 2026-10-12 08:00 UTC; launcher/resources 1791633600 =
  2026-10-10 12:00 UTC), `--root-owner-group`, sorted md5sums, xz, `gzip -9n`.
* Two independent builds give identical `SHA256SUMS`.
* The eight packages whose version is unchanged are **byte-identical** to the .debs delivered earlier
  and installed on the development Pi. Verification builds of task-mesh 0.3.1 and task-console 0.2.0
  are byte-identical too, which shows the builder reproduces the delivered releases.

## Versions

| Package | Version | Pi (dpkg-query 2026-11-08) | Note |
|---|---|---|---|
| python3-task-comms | 0.3.1 | 0.3.1 | byte-identical |
| task-core | 0.3.0 | 0.3.0 | byte-identical; system unit shipped, never enabled |
| task-core-compat | 0.3.0 | 0.3.0 | byte-identical |
| task-console | **0.2.1~alpha1 (PROPOSED)** | 0.2.0 | adds the missing `python3-pyside6.qtnetwork` dependency (see below); payload = Pi except changelog |
| task-aprs | 0.1.0 | 0.1.0 | byte-identical |
| task-sdr | 0.2.4 | 0.2.4 | byte-identical |
| task-mesh | **0.3.2~alpha1 (PROPOSED)** | 0.3.1 + hand-modified notifier | ships the Pi's notifier as maintained source; payload = Pi except changelog; user unit shipped, never enabled |
| task-launcher | 0.3.7 | 0.3.7 | byte-identical |
| task-maps | 0.1.1 | 0.1.1 | byte-identical |
| task-resources | 0.2.4 | 0.2.4 | byte-identical |

`~alpha1` sorts below the final version, so a later 0.3.2 / 0.2.1 release upgrades cleanly.
Both proposed versions need maintainer approval (docs/APPROVALS-NEEDED.md).

### Dependency bug found (task-console 0.2.0)
`task_console/core_client.py` imports `PySide6.QtNetwork`, but 0.2.0 depends only on qtcore/qtgui/qtwidgets.
In the arm64 chroot, task-console installed alone fails to import. On the Pi it works only because
task-launcher depends on `python3-pyside6.qtnetwork`. 0.2.1~alpha1 adds the dependency; no code change.
A static import-vs-Depends scan of all ten packages found no other missing dependency.

## Dependencies: PENDING pins

Dependency lower bounds are unchanged from the delivered packages (`python3 (>= 3.11|3.13)`,
`python3-pyside6.* (>= 6.8)`, …). **Exact versions installed on the Pi for the Debian/Raspberry Pi OS
dependencies are PENDING.** The 2026-11-08 inventory only covers the T.A.S.K. packages and bluez, direwolf,
gpsd, sound-theme-freedesktop and pulseaudio-utils. Pinning, and the Milestone D offline dependency
closure, need this output from the Pi (read-only):

```
dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\t${Status}\n' \
  'python3' 'python3-pyside6*' 'libpyside6*' 'libshiboken6*' 'libqt6*' 'qt6-*' 'python3-yaml' 'python3-pyudev' \
  'python3-serial' 'python3-pubsub' 'python3-protobuf' 'python3-requests' 'python3-tabulate' 'python3-packaging' \
  'python3-pycryptodome' 'python3-jeepney' 'python3-numpy' 'python3-scipy' 'librtlsdr0' 'python3-libzim' \
  'fonts-inter' 'xdg-utils' 'gpsd' 'direwolf' 'rain-*' 2>&1
```

The chroot's resolved versions are in `chroot-results.json` / logs. They are what Debian 13 arm64
provides today, not what the Pi runs (Raspberry Pi OS adds `+rpt` builds of some libraries).

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
* errors: `bogus-mail-host-in-debian-changelog` / `malformed-contact`: placeholder maintainer `TBD-maintainer-email`.
* warnings: `extended-description-line-too-long`, `no-manual-page`, `debian-changelog-line-too-long`,
  `appstream-metadata-validation-failed` (task-mesh metainfo).

## Placeholders reported to the licence audit (not changed here)

* `Maintainer: T.A.S.K. Development Team <TBD-maintainer-email>` in every package.
* Shipped `copyright` files: `Source: T.A.S.K. (Tactical Access Support Kit) — upstream URL TBD`
  (comms, core, compat, console, aprs, sdr, mesh); `Source: R.A.I.N. project (rain-core repository, directory …/)`
  (launcher, maps, resources: outdated project name, no URL).
* `mesh/packaging/debian/copyright` (source tree only, not used by the builder): `Source: https://example.invalid/task-mesh`
  and the "T.A.S.K. Mesh Operations contributors" holder (approval #2).
