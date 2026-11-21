> HISTORICAL / SUPERSEDED for integration and safety decisions by SOURCE-RECONCILIATION-r3.1.md, ARCHITECTURE.md and ADAPTER-API-SPEC.md. Retained for history only; no commands or capabilities here authorize action.

# T.A.S.K. Radio (task-radio): Phase 5A Milestone A r3, reconciliation with the verified Pi inventory

Status: **documents only.** No code was written. Nothing was installed, nothing was run on the Pi, and nothing was transmitted.
Inputs: Joshua's t68u command output and the t69u verified inventory (Pi 5 arm64, Debian 13.6 Trixie, kernel 6.18.34+rpt-rpi-2712, host `box`, user `dragon`), plus the r2 docs (commit 4ca2d34).
Rule: **the Pi is authoritative.** Sources under `/workspace` (aprs/, comms/, task_core/, /workspace/task-mesh) are tagged **pre-install copy, may differ from the Pi**. No interface of task-core, task-comms or task-aprs is treated as confirmed until the installed source has been reviewed.
Labels: VERIFIED (from Joshua's Pi output) · PRE-INSTALL COPY · ASSUMPTION · **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**

---

## 1. Inventory compared with r2

| Item | r2 assumed | Pi (VERIFIED) | Result |
|---|---|---|---|
| task-core | 0.3.0 | 0.3.0, task-core.service active, enabled | match |
| task-core-compat | not tracked | 0.3.0 installed | **new**: must be preserved; files needed (§5) |
| python3-task-comms | 0.3.x pre-install copy | 0.3.1 | the copy may differ, so review is needed |
| task-aprs | "installed?" | 0.1.0 (agw, amateur, kiss, dwconf, config, service, gmrs/driver, gmrs/service) | installed; **KISS/AGW ports unknown** |
| task-mesh | 0.3.1 | 0.3.1 **plus a hand-modified notifier.py** (audio) | the installed file is newer than any packaged source (§8) |
| task-launcher / console / maps / resources / sdr | 0.3.7 / 0.2.0 / 0.1.1 / 0.2.4 / 0.2.4 | same | match |
| BlueZ / Direwolf / bleak / dbus-fast | 5.82 / 1.7 / 0.22.3 / 2.44.1 | same | no new dependency needed for RFCOMM |
| RFCOMM sockets in system Python | assumed | `AF_BLUETOOTH=31, BTPROTO_RFCOMM=3` | VERIFIED available |
| `rfcomm` utility | unknown | /usr/bin/rfcomm | present; r3 does **not** use rfcomm bind/connect |
| UV-PRO XX:XX:XX:XX:XX:XX (redacted) | "known device" | paired yes, bonded yes, **trusted no**, connected no, blocked no, SPP UUID 0x1101 advertised | the KISS protocol and the RFCOMM channel are **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST** |
| UV-PRO firmware | unknown | unknown | blocked |
| Heltec V3 (CP2102, ttyUSB0) | on deny-list | owned by task-mesh-service (user unit, active, **not enabled**) | consistent |
| u-blox 7 (ttyACM0) | "gpsd or direct?" | **gpsd.service active** with by-id path | r2 deny-list stays; r3 GPS goes through gpsd only |
| `dragon` groups | — | includes dialout, audio, plugdev | serial works without root; no group changes |

Note: the u-blox by-id name appears differently in t68u (`usb-u-blox_AG_-_www.u-blox.com_u-blox_7_-_GPS_GNSS_Receiver-if00`, raw `ls` output) and in t69u (underscores stripped by formatting). task-radio never opens this device either way. The `ls` output is treated as the literal name.

## 2. Conflicts with installed components, and how r3 resolves them

| # | r2 item | Conflict | r3 resolution |
|---|---|---|---|
| C1 | `kiss_serial` adapter + `python3-serial` Recommends | could open /dev/ttyUSB0 or ttyACM0 directly | Both devices are **hard-denied by by-id path** and by VID/PID. `kiss_serial` is **deferred** past Milestone B and the `python3-serial` Recommends is dropped (rule 10). |
| C2 | r2 own `kiss/` framer + AX.25 codec | duplicates `task_aprs/kiss.py` and `task_comms/aprs.py` (`kiss_frame`, `encode_ax25` in the pre-install copy) | Reuse when the installed versions are compatible (§4). The offline codec in Milestone B is written as a **test oracle/adapter behind an interface**, and the installed functions are wired in after review. Never two encoders in production. |
| C3 | r2 Direwolf-port deny-list "8000/8001" | assumed Direwolf defaults (the pre-install `kiss.py` defaults port=8001; `dwconf.py` parses `KISSPORT`/`AGWPORT`) | Ports come **only** from the installed task-aprs/Direwolf config (§5). task-radio never connects to Direwolf ports in B. |
| C4 | own TX gate / rate limits | duplicates `task_comms.txpolicy` (pre-install: `TxPolicy.evaluate_amateur`, `TxRequest`, `AmateurConfig`, `Decision`) | `TxGuard` is only a session/enable state machine (token, KILL, TTL). Every legality, rate and duplicate decision is **delegated to installed txpolicy** once reviewed. |
| C5 | own ownership checks | duplicates `task_comms.ownership` (pre-install: `holders()`, `DeviceClaim`) | Use DeviceClaim with key `bt:XX:XX:XX:XX:XX:XX (redacted)`. No new lock dir. The task-mesh lock is only read. |
| C6 | own notifications | duplicates `task_comms.notifications`; Mesh now has a working audio notifier | task-radio emits events only through task_comms (events/notifications) after review. It **does not** play sounds and does not touch Mesh's notifier or sound file. |
| C7 | GPS position for beacons | a direct tty would collide with gpsd | GPS only through gpsd (localhost:2947 via the existing T.A.S.K. integration, which is to be reviewed). There are no beacons in B anyway (Q5). |
| C8 | tile `task.radiolink` + task-core module | overlaps `/usr/lib/task-core/modules/radio.yaml` and the existing `task.radio` tile (task-aprs) | No task-core module file and **no tile** are shipped until Joshua approves. Whether radio.yaml already covers Radio Link is decided after reading it (§5). Default: a standalone app, no tile. |
| C9 | r2 GMRS profile | GMRS already lives in `task_aprs/gmrs/*` | task-radio adds **no GMRS TX**. GMRS stays in task_aprs/gmrs, separate from amateur APRS. |
| C10 | r2 "Scan" button (BlueZ discovery) | changes adapter discovery state, which other apps (LinkBuds S audio) share | Removed from B. Discovery reads existing BlueZ objects only (read-only D-Bus). |
| C11 | assumption that SPP 0x1101 = KISS | Joshua: do not assume | The transport verdict stays `UNVERIFIED` until the controlled test in §6, stage C. |
| C12 | `trust` / auto-connect | Trusted=no; must not change | task-radio never calls Trust/Pair/Connect profile methods on BlueZ. It opens an RFCOMM socket only when the user presses Connect, after approval. Whether that works with Trusted=no is **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**. |

No conflict was found with task-sdr, task-maps, task-resources, task-console, task-launcher or task-core.service, because task-radio modifies none of them.

## 3. Device and service ownership matrix

| Resource | Owner (current) | task-radio access | Notes |
|---|---|---|---|
| Heltec V3 `/dev/serial/by-id/usb-Silicon_Labs_CP2102_..._0001-if00-port0` → ttyUSB0 | **task-mesh-service** (user unit, active, disabled at boot) | **none, ever** (deny-list) | Rule 1–2 |
| u-blox 7 `/dev/serial/by-id/usb-u-blox_AG_..._GPS_GNSS_Receiver-if00` → ttyACM0 | **gpsd.service** | read position from gpsd only, read-only | Rule 4 |
| UV-PRO BT `XX:XX:XX:XX:XX:XX (redacted)` (paired, bonded, **not trusted**, not connected) | nobody | **task-radio only after explicit approval**, user-initiated connect, DeviceClaim `bt:<MAC>` | KISS/channel **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST** |
| LinkBuds S `XX:XX:XX:XX:XX:XX (redacted)` | desktop audio | none | ignored by profile matching |
| BlueZ adapter `XX:XX:XX:XX:XX:XX (redacted)` + `/etc/bluetooth/*` | system / bluetoothd | read-only D-Bus; **config never touched** | no Discoverable/Pairable/Trust changes |
| Direwolf + its KISS/AGW ports | **task-aprs** (via its generated conf; path to be confirmed) | none in B | task-radio never starts or stops Direwolf |
| task-aprs app and `task.radio` tile | task-aprs / task-launcher | none | untouched |
| task-core.service + modules/*.yaml | task-core 0.3.0 | none in B; a client later, only after API review | no changes |
| task-core-compat | task-core-compat 0.3.0 | none | preserved |
| task-mesh notifier.py (modified) + mesh-alert.wav | task-mesh (hand-patched, hardware-verified) | none | §8 |
| gpsd.service | system | client only | no enablement changes |
| `/dev/rfcomm*` | none exist | not used (sockets, not rfcomm bind) | |
| radio-protocols.json, usgs-topo.mbtiles, phase4g backup, Kiwix/library | their packages | none | preserved |

task-radio ships **no systemd unit, no autostart and no udev rule**.

## 4. Integration plan (all pending source review on the Pi)

**task-aprs (0.1.0):**
- `kiss.py`: pre-install copy is a TCP `KissClient(host, port=8001, ...)` with `send_raw(channel, frame)`. Plan: reuse its **frame (un)escaping** if it is exposed as functions. Its TCP client is Direwolf-specific, so task-radio needs a byte-stream transport (RFCOMM). The idea is to reuse the codec and supply our own transport, *if* the installed kiss.py separates the two; if not, request a small refactor in task-aprs (a separate, approved change).
- `amateur.py`: reuse for amateur APRS message/position formatting and parsing where compatible.
- `agw.py`, `dwconf.py`, `service.py`, `config.py`: task-radio does not use AGW. `dwconf.py` is read only to learn the ports, so we never collide with them.
- `gmrs/driver.py`, `gmrs/service.py`: stay **separate**; task-radio does not import them for amateur paths.
- Two apps on one radio: the UV-PRO is reachable only over BT. task-aprs (Direwolf soundcard path) and task-radio would not share a device unless task-aprs is also configured for it. To be confirmed from the installed config.

**task-comms (0.3.1):**
- `ownership.py`: DeviceClaim for `bt:<MAC>`; `holders()` for any tty (none in B).
- `txpolicy.py`: the single source of TX legality, rate and duplicate decisions; GMRS rules untouched.
- `notifications.py`: received messages and TX status go through it (respects quiet hours, mute and focus). No sounds of task-radio's own.
- `bridge.py`: **no forwarding/bridging** from task-radio (rule 7). It is read only to make sure task-radio does not register as a bridge endpoint by accident.
- `events.py` / `status.py` / `core.py`: publish RX packets (payload kept separate from ReceptionMeta) and link status, once the event schema is reviewed.
- `aprs.py`: candidate shared encoder (`kiss_frame`, `encode_ax25` in the pre-install copy). Choose aprs.py or task_aprs/kiss.py, never both, after review.

**task-core:** no module file in B. The radio.yaml content decides whether task-radio is registered there later (approval needed).

## 5. Exact Pi files needed, and a read-only bundling command

Needed:
- `task_core/*` (api, protocol_v2, bus, capabilities, devices, enumerator, modules, sessions, auth, socketpath)
- `/usr/lib/task-core/modules/*.yaml`
- every file from `dpkg -L` of **task-core, task-core-compat, python3-task-comms, task-aprs, task-mesh**, including the docs COMMS-STATUS.md, NOTIFICATIONS.md and GMRS-HARDWARE-RESEARCH.md
- the Direwolf conf that task-aprs uses
- the modified `notifier.py` and its `.pre-audio-backup`
- metadata for `mesh-alert.wav` (the WAV itself is optional, 1.1 MB)

Effect on the Pi: it **only reads** system files and **writes one directory and one tarball in ~**. It uses no sudo and changes no services, packages, configs or devices. Files that are not world-readable are listed as unreadable rather than escalated.

```bash
OUT="$HOME/task-r3-sources-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$OUT"
dpkg-query -W -f='${Package}\t${Version}\t${Status}\n' 'task-*' 'python3-task-*' bluez direwolf gpsd sound-theme-freedesktop pulseaudio-utils > "$OUT/versions.txt" 2>&1
for p in task-core task-core-compat python3-task-comms task-aprs task-mesh; do dpkg -L "$p" > "$OUT/dpkg-L-$p.txt" 2>&1; dpkg --verify "$p" > "$OUT/dpkg-verify-$p.txt" 2>&1; done
cat "$OUT"/dpkg-L-*.txt | while IFS= read -r f; do [ -f "$f" ] && echo "$f"; done | sort -u > "$OUT/filelist.txt"
ls /usr/lib/task-core/modules/*.yaml >> "$OUT/filelist.txt" 2>/dev/null
for f in /usr/lib/task-mesh/task_mesh/hub/notifier.py /usr/lib/task-mesh/task_mesh/hub/notifier.py.pre-audio-backup /etc/direwolf.conf; do [ -f "$f" ] && echo "$f" >> "$OUT/filelist.txt"; done
find "$HOME/.config" "$HOME/.local/share" -maxdepth 3 \( -iname '*direwolf*' -o -path '*task-aprs*' -o -path '*task_aprs*' \) -type f -size -1M 2>/dev/null >> "$OUT/filelist.txt"
grep -rnI -e KISSPORT -e AGWPORT -e 'direwolf' -e '\.conf' $(grep -E '/task_aprs/.*\.py$' "$OUT/filelist.txt") > "$OUT/aprs-port-refs.txt" 2>&1
pgrep -a direwolf > "$OUT/direwolf-proc.txt" 2>&1; ss -ltnp > "$OUT/listening.txt" 2>&1
S="$HOME/.local/share/task-mesh/sounds/mesh-alert.wav"; ls -l "$S" > "$OUT/mesh-sound.txt" 2>&1; sha256sum "$S" /usr/lib/task-mesh/task_mesh/hub/notifier.py /usr/lib/task-mesh/task_mesh/hub/notifier.py.pre-audio-backup >> "$OUT/mesh-sound.txt" 2>&1
diff -u /usr/lib/task-mesh/task_mesh/hub/notifier.py.pre-audio-backup /usr/lib/task-mesh/task_mesh/hub/notifier.py > "$OUT/notifier-audio.diff" 2>&1
while IFS= read -r f; do [ -r "$f" ] || echo "UNREADABLE $f"; done < "$OUT/filelist.txt" > "$OUT/unreadable.txt"
tar --ignore-failed-read -czf "$OUT.tar.gz" -T "$OUT/filelist.txt" -C "$HOME" "$(basename "$OUT")" 2>"$OUT.tar-warnings.txt"
ls -l "$OUT.tar.gz"; sha256sum "$OUT.tar.gz"; cat "$OUT/unreadable.txt" "$OUT/direwolf-proc.txt"
```
Send back the tarball, its sha256 and the last lines of output. If Joshua wants the WAV as well, run `cp ~/.local/share/task-mesh/sounds/mesh-alert.wav "$OUT/"` before the `tar` line (read-only for the source). `dpkg --verify` is read-only. It will flag `notifier.py` as modified, which is expected and confirms what has diverged from the package.

## 6. Next hardware validation (staged; each stage needs Joshua's go-ahead)

**Stage A — read-only and local, with no radio contact (safe now):**
```bash
bluetoothctl info XX:XX:XX:XX:XX:XX (redacted)
bluetoothctl show | grep -E 'Powered|Discover|Pairable'
ls -l /dev/rfcomm* 2>/dev/null; rfcomm -a 2>&1
which sdptool btmgmt 2>&1; dpkg -S "$(command -v sdptool 2>/dev/null)" 2>&1
systemctl is-active task-core gpsd; systemctl is-enabled task-core gpsd
systemctl --user is-active task-mesh-service; systemctl --user is-enabled task-mesh-service
pgrep -a direwolf; ss -ltnp 2>/dev/null | grep -E 'direwolf|:80[0-9][0-9]\b'
/usr/bin/python3 -c "import socket;print(hasattr(socket,'BDADDR_ANY'), socket.AF_BLUETOOTH, socket.BTPROTO_RFCOMM)"
```

**Stage B — SDP service discovery (APPROVAL REQUIRED):**
```bash
sdptool browse XX:XX:XX:XX:XX:XX (redacted)
sdptool records XX:XX:XX:XX:XX:XX (redacted)
```
An SDP query opens a **brief Bluetooth baseband/L2CAP connection** to the radio (2.4 GHz Bluetooth). It does **not** key the radio's VHF/UHF transmitter and sends nothing on amateur or GMRS bands. It does not change pairing, trust or radio settings. It still "contacts" the radio, so it needs explicit approval. The radio must be on and in range. `sdptool` is deprecated in BlueZ 5 and may not be installed. If it is missing, **do not install anything**; report back and we will choose another read-only method. The goal is the RFCOMM channel number(s) behind SPP 0x1101 and any vendor UUIDs.

**Stage M — manual:** read the UV-PRO firmware version on the radio, or in the vendor app's device-info screen. Where it is shown is **UNVERIFIED** (I have not confirmed the menu path). Change no settings. Also report whether a "KISS TNC" or similar Bluetooth option exists and its current state, by **looking only**.

**Not permitted until approved:** `rfcomm connect/bind`, `bluetoothctl trust/untrust/pair/remove/connect`, enabling KISS on the radio, any write to an RFCOMM socket.

**Stage C (later, separate approval) — receive-only KISS test plan:**
1. Preconditions: Stage B gave the channel; Joshua has enabled KISS on the radio himself (if it exists); the radio is on 144.390 MHz, receive; Direwolf/task-aprs are left as they are.
2. The test tool opens `socket(AF_BLUETOOTH, SOCK_STREAM, BTPROTO_RFCOMM)` to `(MAC, channel)` from `/usr/bin/python3`. **It contains no `send`/`write` call** (verified by code review and grep). It logs raw bytes with timestamps for 10–15 minutes, then closes.
3. Pass: well-formed KISS frames (FEND-delimited, data command 0x00) that decode as AX.25 UI APRS packets matching what Direwolf/SDR receives at the same time. Fail or unknown: anything else is recorded as "not KISS / unknown". No guessing.
4. TX test (Milestone D): only after the Q1–Q7 answers, with a dummy load and/or a second station, Joshua's callsign, and one frame per explicit click.
Every result is **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST** until Joshua reports it.

## 7. The seven transmit questions (from Oct 30, reproduced)
1. **TX persistence/timeout:** TX enablement is never persisted (off at every start, link loss, device/profile change and KILL) and expires after **60 minutes idle** (adjustable up to 8 h). OK?
2. **Retries/path:** message retries at **t=0, +30, +60, +120, +240 s** (5 transmissions max, then timed-out; one manual re-try round allowed), default path **`WIDE1-1,WIDE2-1`** (choices: none / WIDE1-1 / WIDE1-1,WIDE2-1). OK?
3. **Auto-ack:** should task-radio automatically ack APRS messages addressed to your callsign-SSID while TX is enabled (still subject to txpolicy), or ask each time?
4. **Reply-acks:** should it send APRS 1.1 reply-acks (`{MM}AA`) or only classic acks?
5. **Beaconing in Milestone B:** **r3 default: none** (no position, status or object beacons, per your rule 7). Do you want any beaconing later, and in which milestone?
6. **Simulator packaging:** ship the simulator as a separate `python3-task-radio-sim` package (not a runtime dependency), or keep it source/test-only?
7. **Milestone D:** which callsign/SSID should be used, is a second station available to receive and ack, and is a dummy load available for the TX tests?

## 8. Preserving the working Mesh audio modification
1. **Canonical source = the Pi.** The installed `/usr/lib/task-mesh/task_mesh/hub/notifier.py` (from the §5 bundle, with its sha256 recorded) replaces the notifier in the task-mesh source tree. The `/workspace/task-mesh` copy is a **pre-install copy, may differ from the Pi** and is never used as the base.
2. Port it with the diff against `.pre-audio-backup` as the review record. Add tests for: `suppress-sound=True` hint set; paplay invoked asynchronously (subprocess list args, **no shell=True**, with `/usr/bin/paplay` mocked); a missing WAV or paplay falls back silently; quiet hours, sound-disabled, muted conversation, focus suppression and dedup all suppress playback.
3. **Version bump to task-mesh 0.3.2.** Never build or ship anything that is ≤0.3.1 or lacks the audio code.
4. **Install guard** in the release script: before any task-mesh install, compare the installed notifier.py sha256 with (a) the 0.3.1 package md5 (`dpkg --verify`) and (b) the Pi-verified audio sha256. If the file matches neither, abort and do not overwrite. Refuse downgrades (the existing installer already does).
5. **Conffiles:** `/usr/lib/...` is not a conffile, so dpkg would silently replace the hand-patched file on upgrade. That is why 0.3.2 must contain the identical audio code, and why the guard backs up the live file to the task-backups dir first. The sound file in `~/.local/share` is user data. Packages never write or delete it. 0.3.2 may ship a default under `/usr/share/task-mesh/sounds/` and use the user copy if present.
6. **Licensing (checked, not guessed):** Debian's copyright file for `sound-theme-freedesktop` (metadata.ftp-master.debian.org, unstable_copyright) gives `Files: *` as **CC-BY-3.0 and CC-BY-SA-3.0 and GPL-2 and GPL-2+**, with multiple authors. It does **not** state which licence or author applies to `alarm-clock-elapsed.oga` specifically. **Still open:** read the upstream `CREDITS` file in the sound-theme-freedesktop source (or `/usr/share/doc/sound-theme-freedesktop/` on the Pi) for that file. Until then, treat it conservatively as **CC-BY-SA-3.0**. That is compatible with redistribution in a GPL project as a separate asset, but the derived WAV must stay CC-BY-SA-3.0. The derived WAV needs (a) attribution to the original author(s), (b) a "modified: +26 dB gain, 0.95 limiter, converted to WAV" notice, (c) a licence URI, and (d) a reproducible recipe (source file and version, exact tool command) in `debian/copyright` and `sounds/README`. Joshua is asked for the exact command used to make it.

## 9. Versioned packaging and rollback
- **New package `task-radio` 0.1.0** (arm64/all, GPL-3.0-or-later). Python under `/usr/lib/task-radio/`, launcher script `/usr/bin/task-radio`. **No systemd unit, no autostart, no udev, no BlueZ config, no tile** (the tile is a later separate approval).
- **Depends** only on what is already installed: `python3 (>= 3.13)`, `python3-pyside6.*` as already used by T.A.S.K., `python3-task-comms (>= 0.3.1)`, `task-aprs (>= 0.1.0)` (only if reuse is confirmed), `python3-dbus-fast (>= 2.44)`. **No new third-party packages.** bleak is not needed for the RFCOMM path.
- `python3-task-radio-sim` is optional (Q6), and nothing depends on it.
- Changes no other package's files. Uses the existing hardened installer (arm64 + trixie hard fail, `INSTALL task-radio-0.1.0`, `--no-remove`, rejects Remv/downgrades).
- **Pre-install snapshot:** `dpkg-query -W > ~/task-backups/pre-radio-0.1.0-<ts>/dpkg.txt`, plus sha256 of notifier.py, mesh-alert.wav and radio-protocols.json.
- **Rollback task-radio:** `sudo apt remove task-radio` (remove only, **no autoremove, no purge of others**), then diff `dpkg-query -W` against the snapshot. The only difference allowed is task-radio. User data in `~/.config/task-radio` is kept unless Joshua deletes it.
- **task-mesh 0.3.2 (separate release):** before install, back up the live notifier.py and mesh-alert.wav into `~/task-backups/mesh-0.3.2-<ts>/`. Rollback = reinstall the 0.3.1 .deb **and** restore the backed-up audio notifier (otherwise the 0.3.1 deb would bring back the no-audio version), then restart task-mesh-service only with Joshua's go-ahead.

## 10. Readiness verdict
**Milestone B may begin partially, offline only, on the box (not the Pi), once Joshua says go:**
- a pure KISS framing/escaping + AX.25 UI codec **as a test oracle**, to be replaced by or adapted to task_aprs/task_comms after review
- the simulator (`task_radio_sim`): a simulated UV-PRO KISS stream, failure and reconnect injection
- the TxGuard enable/KILL/TTL state machine, the message-ID/ack/retry scheduler, and the TX status lifecycle, coded against **abstract interfaces** (`OwnershipPort`, `TxPolicyPort`, `EventPort`, `GpsPort`) with fakes
- Qt panels against the simulator. All tests simulated; there is structurally no hardware path.

**Blocked:**
- task-aprs / task-comms / task-core integration (needs the §5 bundle)
- the actual Direwolf KISS/AGW ports
- the RFCOMM channel and whether SPP = KISS (Stage B/C)
- the UV-PRO firmware version (Stage M)
- answers to Q1–Q7
- tile/module approval (`task.radiolink` vs. none)
- the sound-licence detail for the Mesh 0.3.2 packaging
- the maintainer email (still TBD)
