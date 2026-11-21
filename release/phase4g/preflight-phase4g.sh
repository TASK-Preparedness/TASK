#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# T.A.S.K. Phase 4G M1 preflight (task-sdr 0.1.0 -> 0.2.0). READ-ONLY: never opens the SDR, never writes.
set -uo pipefail
export LC_ALL=C
HERE="$(cd "$(dirname "$0")" && pwd)"
say() { printf '%s\n' "$*"; }
ver() { /usr/bin/dpkg-query -W -f='${Status} ${Version}\n' "$1" 2>/dev/null | /usr/bin/awk '$3=="installed"{print $4}'; }
say "== Versions"
for p in task-sdr task-launcher python3-task-comms librtlsdr0 rtl-sdr python3-soapysdr soapysdr0.8-module-rtlsdr \
         python3-numpy python3-scipy python3-pyside6.qtmultimedia; do printf '  %-32s %s\n' "$p" "$(ver "$p" || true)"; done
S="$(ver task-sdr || true)"; LR="$(ver librtlsdr0 || true)"
[ -n "$S" ] && /usr/bin/dpkg --compare-versions "$S" gt 0.2.0 && say "  BLOCKER: task-sdr $S newer than 0.2.0 (no downgrade)"
{ [ -n "$LR" ] && /usr/bin/dpkg --compare-versions "$LR" ge 2.0.2; } && say "  OK librtlsdr0 $LR (V4 support)" \
  || say "  NOTE: librtlsdr0 ${LR:-none} < 2.0.2: apt will need >= 2.0.2 (Debian trixie has it)"
say "== USB (sysfs, read-only; device is not opened)"
for d in /sys/bus/usb/devices/*; do
    [ -f "$d/idVendor" ] || continue
    v="$(<"$d/idVendor")"; p="$(<"$d/idProduct")"
    case "$v:$p" in 0bda:2838|0bda:2832) say "  $v:$p $(cat "$d/manufacturer" 2>/dev/null) / $(cat "$d/product" 2>/dev/null)";; esac
done
/usr/bin/grep -q '^dvb_usb_rtl28xxu ' /proc/modules && say "  WARNING: dvb_usb_rtl28xxu loaded (claims the stick); blacklisting is a manual step" || say "  ok: DVB driver not loaded"
for b in rtl_tcp rtl_fm sdrpp gqrx dump1090; do /usr/bin/pgrep -x "$b" >/dev/null && say "  NOTE: $b running (owns the receiver)"; done
say "== apt simulation (-s, no changes)"
[ -d "$HERE/debs" ] && /usr/bin/apt-get -s install --no-remove "$HERE"/debs/*.deb 2>&1 | /usr/bin/grep -E '^(Inst|Remv|Conf|E:)' | /usr/bin/sed 's/^/  /'
say "Preflight done. Nothing was changed."
