# Third-party notices

T.A.S.K. itself is © 2026 Joshua Sturtz and contributors, licensed
**GPL-3.0-or-later** (see `LICENSE`). This file lists third-party material that is
included in this repository, bundled into packages, or required at run time.

## Included in this repository

| Component | Version | Where | License | Notes |
|---|---|---|---|---|
| meshtastic (Python) | 2.7.11 | `mesh/packaging/vendor/meshtastic-2.7.11-py3-none-any.whl` (vendored into the task-mesh `.deb`) | **GPL-3.0-only** | Unmodified PyPI wheel, SHA-256 pinned in `mesh/packaging/vendor/SHA256SUMS`. Because it is GPL-3.0-only, the combined task-mesh package is distributed under GPL-3.0 (compatible with our GPL-3.0-or-later code). |
| meshcore | 2.3.15 | `mesh/packaging/vendor/` | MIT | Unmodified wheel. |
| pycayennelpp | 2.4.0 | `mesh/packaging/vendor/` | MIT | Unmodified wheel. |
| pyserial-asyncio-fast | 0.16 | `mesh/packaging/vendor/` | BSD-3-Clause | Unmodified wheel. |
| Lucide icons (incl. Feather-derived) | — | `launcher/task_launcher/data/icons/lucide/` | ISC and MIT | Full texts in `launcher/task_launcher/data/icons/lucide/LICENSE`. |
| Contributor Covenant | 2.1 | `CODE_OF_CONDUCT.md` | CC-BY-4.0 | Adapted (reporting channel filled in). |

## Not included — generated on the user's machine

**Mesh audible alert (`mesh-alert.wav`).** The loud alert used on the
development Pi is a modified version of `alarm-clock-elapsed` from the
freedesktop sound theme 0.8 (Debian package `sound-theme-freedesktop`).
Upstream CREDITS: *alarm-clock-elapsed — Copyright: Tim/corsica_s — URL:
http://www.freesound.org/samplesViewSingle.php?id=67091*, licensed
**CC-BY-SA-3.0**. Modifications: +26 dB gain, limiter 0.95, 16-bit PCM WAV.

To respect the ShareAlike/attribution terms without mixing a CC-BY-SA asset into
the GPL source tree, T.A.S.K. ships only the recipe
(`scripts/generate-mesh-alert.sh`), which writes the WAV plus a license/attribution
file next to it. If a future release decides to ship the WAV, it must carry this
attribution, the modification notice and the CC-BY-SA-3.0 license (maintainer decision).

## Run-time dependencies (installed from Debian, not redistributed here)

Python 3, PySide6/Qt 6 (LGPL-3.0 / GPL), PyYAML (MIT), numpy and scipy (BSD),
pyserial (BSD), protobuf (BSD-3-Clause), pypubsub (BSD), pyudev (LGPL-2.1+),
requests (Apache-2.0), tabulate (MIT), packaging (Apache-2.0/BSD),
pycryptodome (BSD/public domain), jeepney (MIT), python-libzim (GPL-3.0),
gpsd (BSD-2-Clause), Direwolf (GPL-2.0), SoapySDR (BSL-1.0), librtlsdr (GPL-2.0),
BlueZ (GPL-2.0+), pulseaudio-utils (LGPL-2.1+), FFmpeg (LGPL/GPL, only for the
optional alert script). An offline bundle that redistributes these `.deb`s must
include each package's `/usr/share/doc/<pkg>/copyright` (they are inside the `.deb`s).

## Never bundled

Radio firmware (including any proprietary T-Deck firmware), map datasets, ZIM
libraries, medical references, FCC/FAA or other datasets. Users obtain these
themselves under their own terms. Items with unclear redistribution rights are
excluded until reviewed.
