# Third-party notices

T.A.S.K. (Tactical Access Support Kit) is Copyright (C) 2026 Joshua Sturtz and
T.A.S.K. contributors. It is free software under the GNU General Public License,
version 3 or (at your option) any later version (`GPL-3.0-or-later`; full text in
[LICENSE](LICENSE)). The T.A.S.K. name and logo are covered by
[TRADEMARK.md](TRADEMARK.md), which does not limit the GPL.

This file lists third-party material that is in this repository, bundled into
T.A.S.K. packages, or used at run time. Each component stays under its own
license, and nothing here changes those licenses. Versions are the ones
pinned in the repository, or installed on the reference Raspberry Pi 5 running
Debian 13 "trixie" (`packaging/debian/reference/pi-dpkg-baseline-20261122.txt`).
Licenses were checked against the component's own license file, its PyPI
metadata or its Debian `copyright` file on 2026-11-24.

## 1. Included in this repository and in T.A.S.K. packages

| Component | Version | Where | Copyright | License |
|---|---|---|---|---|
| meshtastic (Python library) | 2.7.11 | `mesh/packaging/vendor/` wheel; installed inside the `task-mesh` package (`task_mesh/_vendor/`) | Meshtastic Developers / Meshtastic contributors | **GPL-3.0-only** |
| Meshtastic protocol definitions (generated `meshtastic/protobuf/*_pb2.py`, inside the meshtastic wheel) | as in 2.7.11 | inside the wheel above | Meshtastic contributors | GPL-3.0 (meshtastic/protobufs repository `LICENSE`) |
| meshcore (meshcore_py) | 2.3.15 | `mesh/packaging/vendor/`; inside `task-mesh` | Copyright (c) 2025 Florent de Lamotte | MIT |
| pycayennelpp | 2.4.0 | `mesh/packaging/vendor/`; inside `task-mesh` | Copyright (c) 2018-2021 Sebastian Meiling | MIT |
| pyserial-asyncio-fast | 0.16 | `mesh/packaging/vendor/`; inside `task-mesh` | Copyright (c) 2015-2021 pySerial-team | BSD-3-Clause |
| Lucide icons (some Feather-derived) | snapshot | `launcher/task_launcher/data/icons/lucide/` | Copyright (c) 2026 Lucide Icons and Contributors; Copyright (c) 2013-present Cole Bemis | ISC (Lucide) and MIT (Feather); full text in that folder's `LICENSE` |
| Contributor Covenant | 2.1 | `CODE_OF_CONDUCT.md` (adapted) | Contributor Covenant contributors | CC-BY-4.0 |

The vendored wheels are unmodified PyPI files, SHA-256 pinned in
`mesh/packaging/vendor/SHA256SUMS`, and each keeps its own license file in its
`*.dist-info/` directory. The `task-mesh` package leaves out meshtastic's
`tests/` and `analysis/` subpackages. Nothing else is changed.

**What GPL-3.0-only meshtastic means for T.A.S.K. Mesh.** `task-mesh` imports
and bundles meshtastic in the same process, so the `task-mesh` package as a
whole is distributed under **GPL-3.0** (version 3 only, because meshtastic doesn't
offer "or later"). T.A.S.K.'s own Mesh source files are still
GPL-3.0-or-later. When you redistribute `task-mesh`, you must provide the
complete Corresponding Source under GPLv3: this repository at the matching
tag, plus the meshtastic 2.7.11 source.

## 2. Run-time dependencies installed from Debian (not included in this repository)

T.A.S.K. packages *depend on* these Debian packages. They are installed by apt from
Debian or Raspberry Pi OS, and T.A.S.K. doesn't redistribute them. Anyone
who redistributes them, for example in an offline bundle or a preinstalled
image, must include each package's `/usr/share/doc/<package>/copyright` and
meet its license.

| Component | Debian package (reference version) | Copyright (from Debian `copyright`, `Files: *`) | License | How T.A.S.K. uses it |
|---|---|---|---|---|
| Qt 6 / PySide6 (Qt for Python) | `python3-pyside6.*` 6.8.2.1-4; `libqt6*6` 6.8.2 | The Qt Company Ltd. and contributors | PySide6: LGPL-3.0 or GPL-3.0 (with exception); Qt libraries: LGPL-3.0 or GPL-2.0 (other Qt modules vary; see each package) | imported in-process by the GUI apps under LGPL-3.0 |
| Qt WebEngine (Chromium-based) | `libqt6webenginecore6` 6.8.2+dfsg-4 | The Chromium Authors; The Qt Company Ltd. | LGPL-3.0 or GPL-2.0 for Qt's part; Chromium components carry many licenses (see the package `copyright`) | offline library and medical viewers, maps |
| python-libzim | `python3-libzim` 3.6.0-1.1 | 2020 Juan Diego Caballero, Matthieu Gautier | **GPL-3.0-or-later** | imported in-process by `task-resources` (ZIM reader) |
| libzim (C++) | pulled in by `python3-libzim` | openZIM / Kiwix | GPL (Debian trixie `libzim 9.2.3-1.1`: GPL-3+; upstream README: GPL-2.0-or-later) | via python-libzim |
| NumPy | `python3-numpy` 1:2.2.4+ds-1 | 2005-2024 NumPy Developers | BSD-3-Clause | `task-sdr` |
| SciPy | `python3-scipy` 1.15.3-1 | 2003-2025 SciPy Developers and others | BSD-3-Clause | `task-sdr` |
| pySerial | `python3-serial` 3.5-2 | 2001-2020 Chris Liechti | BSD-3-Clause (upstream `LICENSE.txt`; PyPI "BSD") | Mesh, platform layer |
| protobuf (Python) | `python3-protobuf` 3.21.12-11+deb13u1 | 2008-2021 Google Inc. | BSD-3-Clause | used by meshtastic |
| PyPubSub | `python3-pubsub` 4.0.3-7 | 2006-2018 Oliver Schoenborn | BSD-2-Clause | used by meshtastic and `task-mesh` |
| pyudev | `python3-pyudev` 0.24.3-1 | 2010-2013 Sebastian Wiesner | LGPL-2.1-or-later | `task-core`, Mesh device detection |
| PyYAML | `python3-yaml` 6.0.2-1 | 2017-2019 Ingy döt Net; 2006-2016 Kirill Simonov | MIT | `task-core` |
| jeepney | `python3-jeepney` 0.9.0-1 | 2017-2025 Thomas Kluyver | MIT | Mesh desktop notifications (D-Bus) |
| bleak | `python3-bleak` 0.22.3-1 | 2020 Henrik Blidh | MIT | dependency of meshtastic and meshcore |
| dbus-fast | `python3-dbus-fast` 2.44.1-1 | 2022 Bluetooth Devices Authors; 2019 Tony Crisci | MIT | dependency of bleak |
| tabulate | `python3-tabulate` 0.9.0-1 | 2011-2022 Sergey Astanin and contributors | MIT | dependency of meshtastic |
| requests | `python3-requests` 2.32.3 | 2019 Kenneth Reitz | Apache-2.0 | dependency of meshtastic |
| packaging | `python3-packaging` 25.0-1 | 2014-2025 Donald Stufft and individual contributors | Apache-2.0 OR BSD-2-Clause | dependency of meshtastic |
| PyCryptodome | `python3-pycryptodome` 3.20.0 | see Debian `copyright` | BSD-2-Clause AND Unlicense AND MIT (PyPI); Debian `Files: *`: public-domain, other files as listed there | dependency of meshcore |

## 3. Separate programs T.A.S.K. talks to or launches (not included)

These run as **separate programs**. T.A.S.K. talks to them over sockets,
D-Bus, HTTP or the command line, or launches them from a tile. They are
installed separately by the user or by apt, and T.A.S.K. doesn't include them.

| Program | Version checked | Copyright | License (Debian trixie `copyright`, `Files: *`) | How T.A.S.K. uses it |
|---|---|---|---|---|
| Dire Wolf | Pi: `direwolf` 1.7+dfsg-2+deb13u1 | John Langner WB2OSZ | GPL-2.0-or-later | APRS TNC; KISS/AGW over TCP |
| gpsd | Pi: `gpsd` 3.25-5+deb13u1 | Remco Treffkorn, Eric S. Raymond, GPSD project | BSD-2-Clause | GPS over its JSON socket |
| SoapySDR | Pi: `soapysdr-tools` 0.8.1-5+b2 | Josh Blum and others | BSL-1.0 | optional SDR back end |
| SoapyRTLSDR | Debian trixie `soapyrtlsdr` 0.3.3-1 | Charles J. Cliffe, Josh Blum | MIT | optional SDR module |
| librtlsdr / rtl-sdr tools | Debian trixie `rtl-sdr` 2.0.2-2 | Osmocom project, Steve Markgraf and others | GPL-2.0-or-later (library and tools; some build files GPL-3+) | `rtl_fm`, `rtl_power`, `rtl_sdr`, `rtl_tcp` run as processes |
| kiwix-tools (`kiwix-serve`) | Debian trixie `kiwix-tools` 3.7.0-1.1 | 2009-2019 Emmanuel Engelhart | GPL-3.0-or-later | offline library server over HTTP |
| BlueZ | Pi: `bluez` 5.82-1.1+rpt1 | Intel Corporation and others | GPL-2.0-or-later | Bluetooth daemon over D-Bus |
| PulseAudio utilities (`paplay`) | Pi: `pulseaudio-utils` 17.0+dfsg1-2+rpt1 | PulseAudio developers | LGPL-2.1-or-later | plays the Mesh alert sound |
| FFmpeg | Pi: `ffmpeg` 7.1.5-0+deb13u1+rpt1 | FFmpeg developers | LGPL-2.1-or-later source with optional GPL parts; Debian's default binaries are GPL-2.0-or-later (per its `copyright`) | **only** in the optional `scripts/generate-mesh-alert.sh` |
| SDR++ | not packaged in Debian trixie; installed by the user | SDR++ authors (AlexandreRouma/SDRPlusPlus) | GPL-3.0 (GitHub license of the upstream repository) | launcher tile |
| Gqrx | Debian trixie `gqrx-sdr` 2.17.6-2 | Alexandru Csete OZ9AEC | GPL-3.0-or-later | launcher tile |
| Xastir | Debian trixie `xastir` 2.2.0-1 | Frank Giannandrea, The Xastir Group | GPL-2.0-or-later | launcher tile |

## 4. Not included: generated on the user's machine

**Mesh audible alert (`mesh-alert.wav`): not shipped.** The loud alert is
a modified copy of `alarm-clock-elapsed` from the freedesktop sound theme
0.8 (Debian package `sound-theme-freedesktop`). Upstream CREDITS:
*alarm-clock-elapsed — Copyright: Tim/corsica_s — URL:
http://www.freesound.org/samplesViewSingle.php?id=67091*. The license is
**CC-BY-SA** ("relicensed with permission from author" per CREDITS; Debian
lists CC-BY-SA-3.0). Modifications: +26 dB gain, limiter 0.95, 16-bit PCM WAV.

T.A.S.K. ships only the recipe (`scripts/generate-mesh-alert.sh`). It
builds the WAV on the user's own machine, from the user's own copy of the
Debian package, and writes the attribution and license file next to it. The
sound file isn't in this repository or in any T.A.S.K. package.

## 5. Never bundled

T.A.S.K. never includes radio firmware (Meshtastic, MeshCore or vendor
firmware), map tiles or datasets, ZIM libraries, medical references, or FCC,
FAA and similar datasets. Users get these themselves, under each work's
own license. Public-domain U.S. Government reference snapshots used by the
SDR overlays keep their provenance files in `sdr/overlays/sources/`.

## 6. If you build a Windows bundle or a preinstalled image

* **Qt / PySide6 (LGPL-3.0).** A bundle that includes Qt must meet LGPL-3.0
  section 4. It must give prominent notice that Qt is used and covered by
  the LGPL, include copies of the GPL and LGPL texts, show Qt's copyright
  notice among any copyright notices it displays, and let users replace
  Qt, for example by shipping Qt as separate, replaceable DLLs in a PyInstaller
  "one-folder" build. It must also provide Qt's source or a valid offer for
  it. T.A.S.K. itself is GPL, so its own source is already available.
* **PyInstaller** is GPL-2.0-or-later with a Bootloader Exception. The
  exception allows bundled applications under any license.
* **Preinstalled hardware kits.** These are "User Products" under GPLv3
  section 6. Whoever sells a device with T.A.S.K. preinstalled must provide
  the Corresponding Source, or a written offer for it, and the Installation
  Information needed to install modified versions. Every bundled GPL, LGPL and
  BSD component keeps its notices, including each Debian package's
  `copyright` file.

## 7. Trademarks

Meshtastic® is a registered trademark of Meshtastic LLC. Meshtastic software
components are released under various licenses, see GitHub for details. No
warranty is provided - use at your own risk.

T.A.S.K. refers to Meshtastic, MeshCore and other projects only to describe
compatibility. T.A.S.K. is not affiliated with, sponsored by or endorsed by
Meshtastic LLC, the MeshCore project, or any other project named here.
