#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
#
# Generate the optional loud T.A.S.K. Mesh audible alert ON YOUR OWN MACHINE.
#
# T.A.S.K. does not ship the WAV: it is derived from "alarm-clock-elapsed" in the
# freedesktop sound theme (sound-theme-freedesktop), Copyright Tim / corsica_s
# (https://freesound.org/s/67091/), licensed CC-BY-SA-3.0. The file this script
# creates is a modified version of that work (gain +26 dB, limiter 0.95, 16-bit PCM)
# and stays under CC-BY-SA-3.0 with that attribution. See THIRD_PARTY_NOTICES.md.
#
# Run as your normal user (never root). It never overwrites an existing file (-n).
# Requires: ffmpeg, sound-theme-freedesktop (Debian packages).
set -eu
if [ "$(id -u)" = "0" ]; then
  echo "Run this as your normal desktop user, not root." >&2
  exit 2
fi
SRC=/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga
DEST_DIR="${HOME}/.local/share/task-mesh/sounds"   # path used by task-mesh 0.3.1 notifier
DEST="${DEST_DIR}/mesh-alert.wav"
command -v ffmpeg >/dev/null 2>&1 || { echo "ffmpeg not found (sudo apt install ffmpeg)" >&2; exit 2; }
[ -f "$SRC" ] || { echo "$SRC not found (sudo apt install sound-theme-freedesktop)" >&2; exit 2; }
if [ -e "$DEST" ]; then
  echo "$DEST already exists; leaving it unchanged." >&2
  exit 0
fi
mkdir -p "$DEST_DIR"
ffmpeg -hide_banner -loglevel error -n \
  -i "$SRC" \
  -af "volume=26dB,alimiter=limit=0.95" \
  -c:a pcm_s16le \
  "$DEST"
cat > "${DEST_DIR}/mesh-alert.wav.LICENSE.txt" <<'LIC'
mesh-alert.wav - modified from "alarm-clock-elapsed" (freedesktop sound theme 0.8)
Original: Copyright Tim / corsica_s, https://freesound.org/s/67091/
License: Creative Commons Attribution-ShareAlike 3.0 (CC-BY-SA-3.0)
         https://creativecommons.org/licenses/by-sa/3.0/
Changes: gain +26 dB, limiter at 0.95, converted to 16-bit PCM WAV (FFmpeg).
LIC
echo "Created $DEST (CC-BY-SA-3.0, attribution in mesh-alert.wav.LICENSE.txt)."
echo "Note: this alert is loud. Lower your volume before testing with headphones."
