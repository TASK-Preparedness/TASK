# rain-core 0.1.1: in-place update, real-hardware verification, rollback

This is for the Pi 5 (Debian 13 ARM64) that already runs rain-core 0.1.0 installed by `deploy/pi-install.sh`.
Phase 1 is complete only when every check in section 2 passes on that Pi.

Conventions:
- `$` lines run as the user `pi-install.sh --authorize-user` authorized (an administrator in `/etc/rain/auth.toml`, member of `rain-core`). If that login already has the group, you can drop the `sg rain-core -c '…'` wrapper.
- `jq` may not be installed (`sudo apt-get install -y jq`). Every jq check below has a `python3` fallback that needs nothing extra.
- Expected output is shown after `→`.

## 0. What changes on the Pi

Only the `rain_core` Python package in the system python3 (`/usr/local/lib/python3.13/dist-packages/rain_core`) changes, from 0.1.0 to 0.1.1.

These are **not** touched:
- `/etc/rain/auth.toml`, `/etc/rain/core.toml`, `/var/lib/rain/devices.json`
- the `rain-core` user and group
- `/etc/systemd/system/rain-core.service`, `/etc/tmpfiles.d/rain.conf`
- `/usr/lib/rain/{modules,devices}`, `/usr/local/bin/rain-smoke`

`share/` and `deploy/` (other than the two new files) are byte-identical to 0.1.0, so there is nothing else to copy.

## 1. In-place update

```bash
# on your workstation
scp rain-core-0.1.1-update.zip <user>@<pi>:~
# on the Pi
cd ~ && python3 -m zipfile -e rain-core-0.1.1-update.zip . && cd rain-core-0.1.1-dist
sha256sum -c SHA256SUMS                       # → every line "OK"
sg rain-core -c 'rain-smoke devices' > ~/devices-before-0.1.1.json   # snapshot for comparison
sudo sha256sum /var/lib/rain/devices.json /etc/rain/auth.toml /etc/rain/core.toml | tee ~/state-before-0.1.1.sha256
sudo bash ./update-0.1.1.sh
```
(`bash ./update-0.1.1.sh` is used because `python3 -m zipfile -e` does not restore the executable bit.)

Expected tail of the script output:
```
[update-0.1.1] installed rain_core version: 0.1.0
[update-0.1.1] wheel checksum OK
[update-0.1.1] backup: /var/backups/rain-core/<UTC-timestamp>-pre-0.1.1
[update-0.1.1] stopping rain-core
[update-0.1.1] pip install --no-deps --no-index --break-system-packages rain_core-0.1.1-py3-none-any.whl
...Successfully installed rain-core-0.1.1
[update-0.1.1] installed rain_core version: 0.1.1
[update-0.1.1] starting rain-core
{ "v": 1, "id": "1", "ok": true, "result": { "ok": true, "version": "0.1.1", "uid": <rain-core uid, 993 on your Pi>, ... } }
active
[update-0.1.1] devices.json sha256 before=<X> now=<X>
[update-0.1.1] OK: rain-core 0.1.1 running. Backup: /var/backups/rain-core/<UTC-timestamp>-pre-0.1.1
```
The `before=` and `now=` hashes must be identical. If you run the script again it is idempotent: it prints `already 0.1.1; nothing to install`, runs health, and exits 0.

Confirm the state files are unchanged:
```bash
sudo sha256sum -c ~/state-before-0.1.1.sha256  # → 3 × OK
```

## 2. Verification on real hardware

### 2.1 Health and the assignment

```bash
sg rain-core -c 'rain-smoke health' | jq -c '.result | {ok, version, uid}'
→ {"ok":true,"version":"0.1.1","uid":993}

sg rain-core -c 'rain-smoke devices' | jq -c '.result.assignments["gps.primary"]'
→ {"device_id":"dev_74a462923d20f21e","alias":"smoke","connected":true}

sg rain-core -c 'rain-smoke devices' | jq -c '.result.devices[] | select(.logical=="gps.primary") | {id,alias,subsystem,identity_stable,connected}'
→ {"id":"dev_74a462923d20f21e","alias":"smoke","subsystem":"usb-serial","identity_stable":true,"connected":true}

# baseline id set (u-blox, RTL-SDR, CP2102, eth/wlan … whatever is attached now)
sg rain-core -c 'rain-smoke devices' | jq -r '.result.devices[].id' | sort > ~/ids.baseline; cat ~/ids.baseline
```
The baseline must **not** contain `dev_621b7d85c708289b`. A restart clears it, because cold boot never creates it.

python3 fallbacks (no jq):
```bash
sg rain-core -c 'rain-smoke health' | python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]; print(r["ok"], r["version"], r["uid"])'
→ True 0.1.1 993
sg rain-core -c 'rain-smoke devices' | python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]; print(r["assignments"]["gps.primary"])'
→ {'device_id': 'dev_74a462923d20f21e', 'alias': 'smoke', 'connected': True}
sg rain-core -c 'rain-smoke devices' | python3 -c 'import json,sys; [print(d["id"]) for d in json.load(sys.stdin)["result"]["devices"]]' | sort > ~/ids.baseline
```

### 2.2 The two checks used after every step

`CHECK` prints the u-blox count (expect exactly 1) and its state. It also prints the number of ghost entries, meaning entries with VID 1546, PID 01a7, subsystem usb and identity_stable false (expect 0).

jq:
```bash
sg rain-core -c 'rain-smoke devices' | jq -c '[.result.devices[]|select(.vid=="1546" and .pid=="01a7")] | {ublox_entries: length, ghosts: (map(select(.subsystem=="usb" and .identity_stable==false))|length), entries: map({id,subsystem,identity_stable,connected,logical,alias})}'
```
python3 fallback:
```bash
sg rain-core -c 'rain-smoke devices' | python3 -c 'import json,sys; u=[d for d in json.load(sys.stdin)["result"]["devices"] if (d["vid"],d["pid"])==("1546","01a7")]; print("ublox_entries", len(u), "ghosts", sum(d["subsystem"]=="usb" and not d["identity_stable"] for d in u)); [print(d["id"], d["subsystem"], d["identity_stable"], d["connected"], d["logical"], d["alias"]) for d in u]'
```

`IDS` checks that nothing accumulated. With all devices plugged in, it must print nothing:
```bash
sg rain-core -c 'rain-smoke devices' | python3 -c 'import json,sys; [print(d["id"]) for d in json.load(sys.stdin)["result"]["devices"]]' | sort | diff ~/ids.baseline - && echo "ids unchanged"
→ ids unchanged
```

### 2.3 Cycle 1: same port

```bash
# unplug the u-blox
sleep 3; <CHECK>
→ {"ublox_entries":1,"ghosts":0,"entries":[{"id":"dev_74a462923d20f21e","subsystem":"usb-serial","identity_stable":true,"connected":false,"logical":"gps.primary","alias":"smoke"}]}
# replug it into the SAME port
sleep 3; <CHECK>; <IDS>
→ {"ublox_entries":1,"ghosts":0,"entries":[{"id":"dev_74a462923d20f21e","subsystem":"usb-serial","identity_stable":true,"connected":true,"logical":"gps.primary","alias":"smoke"}]}
→ ids unchanged
```
On 0.1.0 this step showed `ublox_entries: 2` and `ghosts: 1` (`dev_621b7d85c708289b`). On 0.1.1 it must show 1 and 0.

### 2.4 Cycle 2: same port again

Repeat 2.3 and expect identical output.

### 2.5 Cycle 3: a different USB port

Unplug, `sleep 3`, CHECK (connected false). Plug into a **different** USB port, `sleep 3`, then CHECK and IDS.
→ the same single `dev_74a462923d20f21e` entry, `connected: true`, `logical: "gps.primary"`, `ghosts: 0`, `ids unchanged`.
The id does not depend on the port: it comes from the by-id link `usb-u-blox_AG_-_www.u-blox.com_u-blox_7_-_GPS_GNSS_Receiver-if00`. On 0.1.0 this would have left a second ghost with a different `usb-path` id.

Optional: confirm that the event semantics are unchanged. The transient parent is still announced and withdrawn as a balanced pair, but it no longer lingers in the list. `events.recent` needs operator, and the authorized user is administrator.
```bash
sg rain-core -c 'python3 -' <<'PY'
import json, socket
s = socket.socket(socket.AF_UNIX); s.connect("/run/rain/core.sock")
s.sendall(b'{"v":1,"id":"1","method":"events.recent","params":{}}\n')
b = b""
while b"\n" not in b:
    b += s.recv(65536)
for e in json.loads(b)["result"]["events"][-8:]:
    print(e["topic"], json.dumps(e["data"]))
PY
```
After a replug, the expected tail is:
1. `device.disappeared {"id": "dev_74a462923d20f21e", "logical": "gps.primary"}`
2. `capability.changed … "no-device"`
3. `device.appeared {"id": "dev_<parent>", "logical": null}`
4. `device.disappeared {"id": "dev_<parent>", "logical": null}`
5. `device.appeared {"id": "dev_74a462923d20f21e", "logical": "gps.primary"}`
6. `capability.changed … "no-provider"`

`dev_<parent>` is `dev_621b7d85c708289b` on the original port. Querying that id with `device.get` now returns `not-found`.

### 2.6 Reboot

```bash
sudo reboot
# after login:
systemctl is-active rain-core                     → active
sg rain-core -c 'rain-smoke health' | jq -r .result.version     → 0.1.1
<CHECK>  → ublox_entries 1, ghosts 0, dev_74a462923d20f21e connected true, logical gps.primary, alias smoke
<IDS>    → ids unchanged
sudo sha256sum /var/lib/rain/devices.json        → same hash as in ~/state-before-0.1.1.sha256
journalctl -u rain-core -b --no-pager | grep -iE 'error|traceback' || echo "no errors"
```
If the GPS is now in the port from cycle 3, that is fine: cold boot gives the same id.

### 2.7 Pass criteria (report these back)

1. health version 0.1.1.
2. `gps.primary` → `dev_74a462923d20f21e`, alias `smoke`, connected true, after the update, after each cycle and after the reboot.
3. connected false 3 s after every unplug, and true 3 s after every replug.
4. `ublox_entries` = 1 and `ghosts` = 0 after every replug, including the different-port cycle and the reboot.
5. `ids unchanged` after every replug and after the reboot.
6. devices.json, auth.toml and core.toml hashes unchanged.

## 3. Rollback to 0.1.0

The `devices.json` format is identical in 0.1.0 and 0.1.1, so normally only the package is swapped back.
```bash
cd ~/rain-core-0.1.1-dist
sha256sum -c SHA256SUMS
sudo systemctl stop rain-core
sudo python3 -m pip install --break-system-packages --no-deps --no-index ./rain_core-0.1.0-py3-none-any.whl
(cd / && python3 -c 'import rain_core; print(rain_core.__version__)')    → 0.1.0
# Only if a state file must be put back exactly as it was before the update:
B=$(sudo sh -c 'ls -1d /var/backups/rain-core/*-pre-0.1.1 | tail -1'); echo "$B"   # the dir is root-only (0700)
sudo sh -c "cd '$B' && sha256sum -c SHA256SUMS"
sudo cp -a "$B/devices.json" /var/lib/rain/devices.json      # cp -a keeps owner rain-core and mode
sudo cp -a "$B/core.toml" "$B/auth.toml" /etc/rain/
sudo systemctl start rain-core
sg rain-core -c 'rain-smoke health' | jq -r .result.version     → 0.1.0
sg rain-core -c 'rain-smoke devices' | jq -c '.result.assignments'
```
The 0.1.0 wheel is built from the `v0.1.0` tag, which is byte-identical to `core/` in `rain-core-phase1.tar.gz`. It is the same code `pi-install.sh` installed. After a rollback, the 0.1.0 ghost behaviour returns. A restart clears any ghost.
