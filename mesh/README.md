# T.A.S.K. Mesh Operations — v0.1.0

Native Qt (PySide6) field-station app for a Raspberry Pi 5 running Debian 13 / Raspberry Pi OS (trixie),
talking to a **Meshtastic radio over USB serial** (design target: Heltec V3 with CP2102 USB-UART — not yet tested on hardware).

License: **GPL-3.0-or-later** (see `LICENSE`). Bundles meshtastic 2.7.11 (GPL-3.0-only) in the `.deb`.

## What v0.1.0 does

* Finds the radio itself: USB serial ports (`ttyUSB*`/`ttyACM*`), `/dev/serial/by-id` preferred,
  `by-path` when two boards share a USB serial number, never assumes `ttyUSB0`, never lets the library
  auto-detect. Several possible radios → you pick one (optionally "Remember this radio").
* Connection state machine in a radio worker thread: scanning, no device, permission denied, port busy,
  connecting, connected, device rebooting, backoff (1, 2, 4 … 30 s), watchdog, hot-plug (udev, with a
  2 s polling fallback when udevd is not running). The GUI never blocks on the radio.
* **Radio panel:** CONNECTED / CONNECTING… / DISCONNECTED badge plus the exact state, local device
  (long/short name, node ID, hardware, firmware if the radio reports it), port (by-id name and `/dev`
  node), last error with the remedy (e.g. the `dialout` command), Connect / Disconnect / Stop /
  Rescan / Retry now, port picker.
* **Node table:** Long Name, Short Name, Node ID, Hardware, Last Heard, RSSI, SNR, Hops, Battery,
  Latitude, Longitude. Unknown values are shown as **—** (never 0). Calculated hops are marked
  **calc**. Battery > 100 shows **Powered**. Tooltips say where each value came from. Sortable,
  kinetic touch scrolling; double-tap or long-press a row for a read-only detail view.
* **Status bar:** nodes known / heard this session, database status (OK / backlog / ERROR, path in
  tooltip), bad-packet counter, Fullscreen (F11).
* SQLite (WAL, migrations, single writer thread, integrity check, corrupt files are moved aside —
  never deleted — retention pruning). Nodes are kept and shown as "last known" after a restart.
* Structured JSON-lines log with key redaction. Works fully offline; no network calls.

**Not in v0.1.0** (nothing in the UI pretends otherwise): maps, messaging/sending, telemetry charts,
waypoints/alerts, gpsd, APRS, BLE/TCP radios, radio configuration, plugins. `task_mesh/mapping`,
`messaging`, `telemetry`, `gps`, `aprs`, `alerts` are empty placeholder packages; `plugins` holds only
the `DataSourcePlugin` interface (no loader).

## Install on the Pi (development .deb)

The `.deb` uses Debian's own Python/Qt packages plus the bundled meshtastic 2.7.11; no pip, no venv.
Build it on the Pi (produces `task-mesh_0.1.0_arm64.deb`) — see "Building the .deb" — or use the
`task-mesh_0.1.0_arm64.deb` cross-built on amd64 (pure Python, same contents; not yet installed on a Pi). Then:

```sh
sudo apt install ./dist/task-mesh_0.1.0_arm64.deb
task-mesh            # or: menu → Internet/Network → "T.A.S.K. Mesh Operations"
```

Serial permission (once per user; the package never changes groups for you):

```sh
groups | grep -q dialout || sudo usermod -aG dialout "$USER"   # then log out and back in
```

Never run the app as root; it refuses to start as root.

## Run from source (no install)

```sh
sudo apt install python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets \
  python3-serial python3-pubsub python3-protobuf python3-pyudev python3-requests \
  python3-tabulate python3-yaml python3-packaging qt6-wayland
python3 -m venv --system-site-packages .venv
.venv/bin/pip install --no-deps meshtastic==2.7.11      # developers only; the .deb bundles it
.venv/bin/python -m task_mesh            # options: --debug --no-autoconnect --version
```

## Files and settings

| What | Where |
|---|---|
| config (optional, read-only for the app) | `${XDG_CONFIG_HOME:-~/.config}/task-mesh/config.toml` |
| remembered radio, last good port | `${XDG_STATE_HOME:-~/.local/state}/task-mesh/state.json` |
| log (JSON lines, rotated 5 × 2 MB) | `${XDG_STATE_HOME:-~/.local/state}/task-mesh/log/task-mesh.jsonl` |
| database | `${XDG_DATA_HOME:-~/.local/share}/task-mesh/task-mesh.sqlite3` |

Example `config.toml` (all keys optional):

```toml
[radio]
autoconnect = true
handshake_deadline_s = 45   # minimum 35
link_probe_s = 120          # write-only heartbeat; 0 disables
reboot_grace_s = 60
[retention]
node_observations_days = 30
connection_events_days = 180
radio_events_days = 30
radio_events_max_rows = 200000
nodes_unheard_days = 0      # 0 = keep forever
[ui]
density = "auto"            # auto | touch | compact
fullscreen = false
[logging]
level = "INFO"              # the meshtastic library is always capped at WARNING
```

To forget a remembered radio, delete the `pinned_port` entry from `state.json` (or the file).
Uninstalling the package does not delete your data; `task-mesh --forget-user-data` does (asks first).

## Troubleshooting

* **PERMISSION_DENIED** — run the `usermod` command above, then log out/in (`id` must list `dialout`).
* **PORT_BUSY** — another program has the port (meshtastic CLI, another client, a second copy).
  Close it; the app retries automatically.
* **No device although plugged in** — check `dmesg | tail` for `cp210x … attached to ttyUSB`, use a
  data-capable cable. If brltty grabs it: `sudo systemctl mask brltty-udev.service` and replug.
* **Display** — Qt uses Wayland when available. Workaround for rendering issues: `QT_QPA_PLATFORM=xcb task-mesh`.

## Development and tests

Tests: pytest + pytest-qt (+ pytest-timeout), offscreen Qt, temporary XDG dirs, fake radios
(no hardware): unit, provider-with-fake-library, contract tests against the real meshtastic 2.7.11
on a pseudo-terminal radio, full-app integration (pty radio + real DB), UI.

```sh
# A) Debian packages only (what the .deb uses):
sudo apt install python3-pytest python3-pytestqt python3-pytest-timeout python3-pyside6.qttest
tools/run_tests_debian.sh -q                 # all tests, incl. slow (~2 min)
tools/run_tests_debian.sh -q -m "not slow"   # fast subset (~1 min)

# B) PyPI venv:
python3 -m venv .venv && .venv/bin/pip install -e '.[test]'
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

Screenshots (offscreen, 1024×600, synthetic pty radio): `python3 tools/screenshot_demo.py docs/screenshots`.
Icon PNGs from the SVG: `python3 tools/render_icon.py`.

## Building the .deb

```sh
sudo apt install build-essential debhelper dh-python dpkg-dev   # dpkg-buildpackage always requires build-essential
packaging/build-deb.sh            # → dist/task-mesh_0.1.0_<arch>.deb (arm64 on the Pi)
```

`Architecture: any` (all code is pure Python): the package built on the Pi is arm64, on a PC amd64.

## Hardware acceptance tests (Pi 5 + Heltec V3) — REQUIRED, not yet performed

These cannot be run without the hardware. Status of every test: `docs/v0.1.0-acceptance-status.md`.
Log file to attach: `~/.local/state/task-mesh/log/task-mesh.jsonl`.

1. **AT-H1 USB identity** — plug in the Heltec, then:
   ```sh
   lsusb | grep -i 10c4                     # expect 10c4:ea60 ... CP210x
   ls -l /dev/serial/by-id/                 # record the name; is the serial "0001"?
   ls -l /dev/ttyUSB*                       # expect crw-rw---- root dialout
   udevadm info -q property -n /dev/ttyUSB0 | grep -E 'ID_SERIAL|ID_PATH|ID_VENDOR_ID|ID_MODEL_ID'
   dmesg | tail -20                         # cp210x converter now attached; no brltty
   ```
2. **AT-H2 interference** — `systemctl status brltty-udev.service ModemManager.service`; plug/unplug 5×
   with `journalctl -f` running: no brltty/ModemManager claims `ttyUSB*`, node stays while plugged.
3. **AT-H2b permissions** — as a user not in dialout launch `task-mesh`: expect PERMISSION_DENIED with
   the remedy. `sudo usermod -aG dialout "$USER"`, log out/in, relaunch: CONNECTED.
   `ps -o user= -C python3` must not show root.
4. **AT-H3 late plug-in** — start with no radio: NO_DEVICE, `top` < 2 % CPU. Plug in: CONNECTED
   within 10 s; panel shows long name, HELTEC_V3, node ID, by-id path.
5. **AT-H4 unplug/replug** — while CONNECTED pull the cable: DISCONNECTED within 3 s, table still
   scrollable and nodes visible. Replug: CONNECTED within 10 s. Repeat 10×. Record the exception
   type logged (`grep -i "disconnected" ~/.local/state/task-mesh/log/task-mesh.jsonl`).
6. **AT-H5 open-time reset** — watch the OLED when connecting; record whether it reboots each time.
7. **AT-H6 device reboot** — press RST while CONNECTED: back to CONNECTED within 60 s, no action.
   Record whether the log shows `DEVICE_REBOOTING` or a port loss + BACKOFF.
8. **AT-H7 multiple devices** — add a second USB serial device. Non-radio: auto-connects to the Heltec.
   Second radio: picker appears, nothing opened until you choose; with "Remember", restart → auto.
   Two Heltecs with by-id serial 0001: tooltip on Port shows `/dev/serial/by-path/...`.
9. **AT-H8 install/uninstall** — `sudo apt install ./dist/task-mesh_0.1.0_arm64.deb` (no pip); menu
   entry + icon; launch from menu and from a terminal. `sudo apt purge task-mesh`; then
   `ls /usr/lib/task-mesh /usr/bin/task-mesh /usr/share/applications/task-mesh.desktop` all missing,
   `dpkg -L task-mesh` reports not installed, and `~/.local/share/task-mesh` still exists.
10. **AT-H9 display** — `echo $XDG_SESSION_TYPE` → wayland; log line `qt.platform=wayland`;
    `QT_QPA_PLATFORM=xcb task-mesh` also works; F11 / Fullscreen button on both; taskbar icon correct.
11. **AT-H10 touch 1024×600** — finger only: connect/disconnect, picker, kinetic scroll 100+ nodes,
    sort by tapping headers, long-press a row: no missed taps in 20 attempts.
12. **AT-H11 live updates** — another node sends position: its Last Heard/SNR/RSSI change within 2 s;
    RSSI is — for nodes not heard since launch. Close the app and compare with `meshtastic --nodes`.
13. **AT-H12 power loss** — pull Pi power while receiving; reboot, relaunch: no corruption banner,
    nodes reload (`grep quick_check` not needed — a banner appears only on corruption).
14. **AT-H13 soak** — 12 h CONNECTED: `ps -o rss= -p $(pgrep -f task_mesh)` growth < 50 MB;
    `ls /proc/$(pgrep -f task_mesh)/task | wc -l` stable across 3 unplug/replug cycles.
15. **AT-H14 port busy** — `meshtastic --port /dev/serial/by-id/<name> --listen` in a terminal, then start
    T.A.S.K.: PORT_BUSY with remedy; stop the CLI: connects within the backoff window (≤ 30 s).
