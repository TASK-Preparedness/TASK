<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# Phase 4A integrations — what is verified, what is assumed

"Verified" here means checked against source code, packaging or upstream documentation on the
development machine. **Nothing in this list has been run on the Pi.** Every hardware-dependent
item is UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.

## Mesh Network — rain-mesh

| Item | State |
|---|---|
| Executable | `/usr/bin/rain-mesh` (verified in the rain-mesh 0.1.0 Debian packaging: `/bin/sh` wrapper running `python3 -I -S -B` with `/usr/lib/rain-mesh`); `/usr/local/bin/rain-mesh` accepted as an alternative (pip/venv install) |
| CLI compatibility | Verified from `rain_mesh/app.py`: no arguments are required; the launcher passes none. `--version`, `--debug`, `--no-autoconnect`, `--forget-user-data` exist and are not used |
| Installed on the Pi? | **No** (given). The tile is Unavailable "not installed: rain-mesh" until it is. The sheet shows a labelled *temporary read-only status* |
| Coexistence with rain-core | rain-mesh opens the Heltec V3 serial port itself (vendored Meshtastic `SerialInterface`, exclusive). It is not a rain-core client. rain-core never opens tty nodes, so Core does not conflict; the meshtastic CLI or a second rain-mesh does. The launcher flags a running `meshtastic` CLI as a serial conflict |
| Single instance | rain-mesh has no single-instance guard of its own; the manifest's `single_instance = true` prevents a second copy from the launcher only |
| Hardware | UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST (rain-mesh deb is arm64, cross-built, never installed on the Pi) |

The `meshtastic` CLI alone never makes the tile Available. The launcher never changes firmware,
channels, keys or any radio setting.

## Maps & GPS

- `/usr/bin/task-maps` (Phase 4B) is the first candidate; until it exists, `/usr/bin/foxtrotgps`
  is used and the tile says **"Available — FoxtrotGPS (fallback)"**.
- gpsmon / cgps (gpsd-clients) are context-menu actions, run in a terminal emulator.
- FoxtrotGPS, gpsmon and cgps talk to gpsd (127.0.0.1:2947), not to rain-core. The readiness
  line shows both rain-core `gps.position` and whether gpsd's port answers a TCP connect.
- GPS fix quality: UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.

## SDR

- SDR++ `/usr/bin/sdrpp`, then Gqrx `/usr/local/bin/gqrx` (both verified present on the Pi
  per the directive). A missing program gives Unavailable "not installed: SDR++, Gqrx"; a start
  failure gives "Error — exited with code N X.X s after start: <last output line>".
- Readiness: from rain-core `device.list` (operator sign-in required): "RTL-SDR 0bda:2838
  present (rain-core)" only when a connected 0bda:2838 is listed. Before sign-in it shows
  `radio.rx` capability status. Display only — the launcher never calls `device.assign`.
- **Bypass:** SDR++ / Gqrx open the dongle via librtlsdr directly; the IQ stream does not go
  through rain-core. rain-core only enumerates (udev) and does not hold the device open, so
  there is no Core conflict today. Other SDR programs visible in `/proc` (sdrpp, gqrx, rtl_fm,
  rtl_tcp, rtl_433, rtl_sdr, rtl_power, dump1090*) are reported "in use by …".
- Reception: UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.

## Library — Kiwix / IIAB

- API verified against the kiwix-tools documentation (readthedocs) for kiwix-tools 3.7.0 /
  libkiwix 14.0.0, the versions in Debian trixie: OPDS `/catalog/v2/entries`, `/search` with
  `books.name` and `format=xml`, `/content/…`, legacy `/catalog/root.xml`.
- IIAB layout verified against the IIAB kiwix role: `kiwix-serve --daemon --port {{kiwix_port}}
  (3000) --nolibrarybutton --library /library/zims/library.xml --urlRootLocation=/kiwix/`.
- Discovery order: systemd units → running processes → IIAB config → documented defaults
  (only if nothing else verified, labelled "default candidate"). Every candidate must answer
  with an Atom feed on 127.0.0.1 before it is shown as working.
- The launcher never starts kiwix-serve (so it cannot start a conflicting second one).
- The actual unit name, port and root on the Pi: **ASSUMED** from IIAB defaults; UNVERIFIED
  until run on the Pi (the window lists every candidate and why it failed).
- The native viewer (QTextBrowser) renders simplified HTML (no scripts, styles, iframes or
  remote resources). Complex pages should use "Open in browser" (xdg-open, loopback URL).

## Radio / APRS — Direwolf

- Read-only status: `/usr/bin/direwolf` presence, processes from `/proc`, systemd units with
  "direwolf" in the name, configs (`~/direwolf.conf`, `/etc/direwolf.conf`, and `-c` from a
  running process / unit ExecStart), and the parsed ADEVICE, ACHANNELS, MYCALL, MODEM, PTT,
  KISSPORT, AGWPORT, beacons, IGSERVER (IGLOGIN passcode masked).
- Ports: KISS (default 8001) and AGW (default 8000) checked with a connect-only probe.
- Monitor: **RECEIVE ONLY**. KISS over TCP → AX.25 UI → APRS (positions, Mic-E, messages,
  objects, items, status, weather, telemetry, third-party). The socket wrapper has no send
  method; tests assert nothing is written.
- The launcher never starts Direwolf. If it is not running, the window says so; setting it up
  (sound card, PTT, callsign) is a manual, licensed-operator task.
- RF reception: UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.

## Medical / Weather

- Medical: Kiwix books whose name/title/tags match medical keywords, IIAB modules under
  `/library/www/html/modules`, and folders in `~/.config/task-launcher/reference.toml`
  `[medical] dirs`. Reference only — no patient data, no clinical claims. Future patient
  records need a separate design (authentication, encryption at rest, audit log, retention).
- Weather: installed decoders (noaa-apt, satdump, wxtoimg, aptdec, rtl_433, acarsdec, dumpvdl2)
  and files in `[weather] dirs` with their age. Never a forecast. See WEATHER-SOURCES.md.
