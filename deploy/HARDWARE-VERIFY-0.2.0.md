<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# rain-core 0.2.0 + rain-console 0.1.0: upgrade, Pi acceptance (PHASE-2.md r3 §17.9), rollback

For the Pi 5 (Debian 13 trixie ARM64, labwc desktop, Kado at 1920×1080) that runs the Pi-accepted rain-core 0.1.1
(tag `phase1-accepted`). Hardware: u-blox 7 (`/dev/ttyACM0`), RTL-SDR Blog V4, CP2102 (`/dev/ttyUSB0`), Heltec V3.

> **Every step in this document is UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.** The off-target automated suite
> (tests 1–92, including the update/rollback simulation, test 77) passed on an amd64 Debian 13 box; nothing here has run
> on the Pi, on real USB hardware, on Wayland/labwc, or on the Kado display. Record each result (pass/fail, output,
> time) in the Phase 2 acceptance record. A required step that is not performed is a blocker (§18).

Conventions (as in `HARDWARE-VERIFY-0.1.1.md`):
- `$` lines run in a terminal **on the labwc desktop**, as your existing desktop user (D2), which is also the smoke uid.
  If your login already has the `rain-core` group, the `sg rain-core -c '…'` wrapper can be dropped.
- A password needed in a shell command is read with `read -rs PW` and cleared with `unset PW`. It is never typed on a
  command line. `rain-core-admin` always prompts with no echo.
- Expected results follow `→`. Example outputs marked *(simulation)* come from the off-target test environment
  (fake devices, a different uid); the Pi values (uid 993, times, `boot_id`, `seq`) will differ.
- Steps 0–16, 18 and 19 are required; step 17 is optional. There is no autostart step and no 7" step (D9).
  Step A (the automated suite on the Pi, §18 item 1) is required too.

`CHECK` (u-blox count and ghosts, expect `ublox_entries:1 ghosts:0`):
```bash
sg rain-core -c 'rain-smoke devices' | python3 -c 'import json,sys; u=[d for d in json.load(sys.stdin)["result"]["devices"] if (d["vid"],d["pid"])==("1546","01a7")]; print("ublox_entries:%d ghosts:%d" % (len(u), sum(d["subsystem"]=="usb" and not d["identity_stable"] for d in u))); [print(d["id"], d["subsystem"], d["identity_stable"], d["connected"], d["logical"], d["alias"]) for d in u]'
```
`IDS` (nothing accumulated; with all devices plugged in it prints `ids unchanged`):
```bash
sg rain-core -c 'rain-smoke devices' | python3 -c 'import json,sys; [print(d["id"]) for d in json.load(sys.stdin)["result"]["devices"]]' | sort | diff ~/ids.phase2.baseline - && echo "ids unchanged"
```

## What changes on the Pi

- `/usr/local/lib/python3.13/dist-packages/rain_core/` 0.1.1 → 0.2.0, and the new command `/usr/local/bin/rain-core-admin`.
- After step 3 (explicit administrator commands): `/var/lib/rain/accounts.json` (0600 rain-core) and `/etc/rain/sessions.toml` (0644 root).
- After step 4 (`install-console.sh`): Debian packages `python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets
  python3-pyside6.qtnetwork qt6-wayland` (**apt needs the network or a local apt cache**), `/usr/local/lib/python3.13/dist-packages/rain_console/`,
  `/usr/local/bin/rain-console`, `/usr/local/share/applications/rain-console.desktop`, `/usr/local/share/icons/hicolor/scalable/apps/rain-console.svg`.
- Step A additionally installs the Debian test packages `python3-pytest python3-pytestqt python3-pyside6.qttest` (and `python3-setuptools`, `python3-pip`, `python3-yaml` if missing).
- **Not touched:** `/etc/rain/auth.toml` (until the intentional D6 edit in step 18), `/etc/rain/core.toml`, `/var/lib/rain/devices.json`,
  the `rain-core` user and group, `/etc/systemd/system/rain-core.service`, `/etc/tmpfiles.d/rain.conf`, `/usr/lib/rain/`, `/usr/local/bin/rain-smoke`.
  No autostart entry, user unit, labwc file, or display-manager change is ever created. The web-station installer is never run.

## Transfer and unpack

```bash
# on your workstation
scp rain-phase2-update.zip <user>@<pi>:~
# on the Pi
cd ~ && python3 -m zipfile -e rain-phase2-update.zip . && cd rain-phase2-dist
sha256sum -c SHA256SUMS                   # → every line "OK"
```
(`bash ./script.sh` is used below because `python3 -m zipfile -e` does not restore the executable bit.)

---

## 0. Pre-flight, including the labwc confirmation (D3)

```bash
echo "$XDG_SESSION_TYPE $XDG_CURRENT_DESKTOP"; pgrep -u "$USER" -x labwc
```
→ `wayland labwc…` and a pid. **If not, stop.** Steps 4–16 wait until a labwc desktop is confirmed.

```bash
id -u; id -nG | tr ' ' '\n' | grep -x rain-core; sudo cat /etc/rain/auth.toml
```
→ your uid; `rain-core`; `[peers]` with `<your uid> = "administrator"` (the desktop user is the smoke uid, §12 item 3).

```bash
sg rain-core -c 'rain-smoke health'
```
→ `"version": "0.1.1"`, `"uid": 993`.

```bash
getent passwd rain; stat -c '%U' /var/lib/rain
```
→ no output for `getent`; `rain-core` (K3). If either differs, **stop**: `update-0.2.0.sh` refuses too.

```bash
sudo sha256sum /var/lib/rain/devices.json /etc/rain/auth.toml /etc/rain/core.toml /etc/systemd/system/rain-core.service | tee ~/phase2-before.sha256
sg rain-core -c 'rain-smoke devices' | python3 -c 'import json,sys; [print(d["id"]) for d in json.load(sys.stdin)["result"]["devices"]]' | sort > ~/ids.phase2.baseline; cat ~/ids.phase2.baseline
sudo -n true 2>/dev/null && echo sudo-nopasswd || echo sudo-password      # record only (§12 item 4)
```
→ 4 hashes saved; the id baseline contains `dev_74a462923d20f21e`, `dev_ca4a208a9242de2c`, `dev_ccbc25d5a4210a5a` (plus whatever else is attached).

## 1. Upgrade 0.1.1 → 0.2.0

```bash
cd ~/rain-phase2-dist && sudo bash ./update-0.2.0.sh
```
Expected tail:
```
[update-0.2.0] K3 pre-flight OK (/var/lib/rain owned by rain-core; no 'rain' account)
[update-0.2.0] installed rain_core version: 0.1.1
[update-0.2.0] wheel checksum OK
[update-0.2.0] backup: /var/backups/rain-core/<UTC>-pre-0.2.0
[update-0.2.0] stopping rain-core
[update-0.2.0] pip install --no-deps --no-index --break-system-packages rain_core-0.2.0-py3-none-any.whl
...Successfully installed rain-core-0.2.0
[update-0.2.0] installed rain_core version: 0.2.0
[update-0.2.0] starting rain-core
<rain-smoke health JSON: "ok": true, "version": "0.2.0", "uid": 993, …>
active
[update-0.2.0] devices.json sha256 before=<X> now=<X>
[update-0.2.0] auth.toml and core.toml sha256 unchanged
[update-0.2.0] OK: rain-core 0.2.0 running. Backup: /var/backups/rain-core/<UTC>-pre-0.2.0
```
Then:
```bash
sudo sha256sum -c ~/phase2-before.sha256                                   # → 4 × OK
sg rain-core -c 'rain-smoke devices' | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["assignments"]["gps.primary"])'
<CHECK>; <IDS>
sg rain-core -c 'rain-smoke health'
```
→ `{'device_id': 'dev_74a462923d20f21e', 'alias': 'smoke', 'connected': True}`; `ublox_entries:1 ghosts:0`; `ids unchanged`;
health `0.2.0`, uid 993 (v1 still works). Running the script again prints `already 0.2.0; nothing to install` and exits 0.

## 2. v2 probe

```bash
rain-core-admin probe
```
→ *(simulation)* `{"core.protocol": {"boot_id": "…", "core": "0.2.0", "versions": [1, 2]}}`, exit 0. No sudo.

## 3. Bootstrap the accounts (D12, D4)

```bash
sudo rain-core-admin user add dragon --role administrator   # paste a password-manager password, ≥20 chars, containing at least one space, at both prompts
sudo rain-core-admin user add op --role operator
sudo rain-core-admin user add short --role operator         # enter 1234567 (7 characters)
```
→ the third is rejected with `password must be 8–256 characters`, and no account is created.

```bash
sudo rain-core-admin client allow "$USER"
sudo rain-core-admin user list
sudo stat -c '%a %U:%G' /var/lib/rain/accounts.json
cat /etc/rain/sessions.toml
sudo sha256sum -c ~/phase2-before.sha256
```
→ `user list` shows exactly `dragon administrator` and `op operator`; `600 rain-core:rain-core`; `sessions.toml` lists your uid
under `[clients]`; 4 × OK.

## A. Automated suite on the Pi (§18 item 1; Debian packages only, as your normal user)

Do this after step 4 has installed the Qt packages (or install them here with the same apt line).
```bash
sudo apt-get install python3-pytest python3-pytestqt python3-pyside6.qttest python3-setuptools python3-pip python3-yaml
cd ~/rain-phase2-dist && tar -xzf rain-phase2-source.tar.gz && cd rain-phase2-src
./run_tests_debian.sh 2>&1 | tee ~/phase2-debian-suite.txt
```
→ `== rain-core` … `N passed`, `== rain-console` … `M passed`, `== both suites passed`; no failures, no errors.
Off-target counts for reference: see `CHANGELOG.md`/the delivery report. Test 77 finds the Pi-accepted 0.1.1 wheel in
`~/rain-phase2-dist/`, the parent of the extracted tree (it checks sha256 `b1935dd7…a26a`). The suite creates only temporary files under `/tmp`; it does
not touch the running rain-core.

## 4. Install and launch manually

```bash
cd ~/rain-phase2-dist && sudo bash ./install-console.sh
```
→ ends `OK. Start it from the application menu (R.A.I.N. Console) or run: rain-console`. It prints the
`usermod -aG rain-core` hint but changes no group (you already have it).

Open **R.A.I.N. Console** from the labwc application menu.
- → a normal decorated window, maximized within the work area: the labwc panel is still visible, and it is **not** fullscreen.
- → `wlr-randr` (or display settings) reports 1920×1080. The log line
  `rain-console 0.1.0 started (socket /run/rain/core.sock, platform wayland, scale 1.0)` appears in
  `~/.local/state/rain-console/console.log` (`grep started ~/.local/state/rain-console/console.log`).
- → Home shows 7 tiles with states identical to `capability.list`/`module.list`
  (`rain-core-admin probe --public | grep -E 'capability.list|module.list'`): e.g. GPS `inactive`, `gps.position no-provider`.
  Nothing shows `available`.
- → `ls ~/.config/autostart 2>/dev/null | grep -c rain` → `0`.

## 5. Public view (D5) — signed out (status strip `Public`)

- → Devices shows only `N connected · M disconnected · T total` and the sign-in prompt. N, M, T match
  `sg rain-core -c 'rain-smoke devices'` (v1 via `[peers]`, still present).
- → Home and the GPS placeholder show logical devices as `Sign in to view`.
- → no `dev_…` id, `/dev/` path, serial, alias, or logical name is visible on any panel.

```bash
rain-core-admin probe --public --stream 15 > ~/public-view.jsonl     # during these 15 s: unplug and replug the u-blox
grep -cE 'dev_[0-9a-f]{16}|/dev/|by-id|usb-path:|gps\.primary|mesh\.primary|sdr\.primary|radio\.primary|smoke|"serial"|"devnode"|"alias"|"logical' ~/public-view.jsonl
grep -c '"device.counts"' ~/public-view.jsonl
```
→ `0`; at least `2`. (v2 without a session is always public, even for a `[peers]` uid.)

## 6. Operator

Sign in as `op` → the device list is visible, with no Assign or Unassign controls, and the text
"Assigning devices requires an administrator."

## 7. Live hot-plug (signed in as `op`)

- Unplug the u-blox → within **3 s** the gps.primary slot shows `Disconnected — assignment kept`; the GPS tile shows `gps.position no-device`.
- Replug → within 3 s `Connected` and `no-provider`. → no extra u-blox row; `<CHECK>` → `ublox_entries:1 ghosts:0`.
- Sign out (Public). Unplug → within 3 s the public counts change (connected −1, disconnected +1) and no device data appears. Replug → counts restored.

## 8. Administrator round trip surviving a reboot

- Sign in as `dragon`, **pasting** the password (D4: paste allowed, spaces preserved).
- Assign `dev_ca4a208a9242de2c` (RTL-SDR) as `sdr.primary`, alias `sdr`. The confirmation shows no displacement.
  → SDR tile `radio.rx no-provider`; Radio tile `radio.tx no-device`.
- `sudo reboot`. Log in, open the console from the menu, sign in as `dragon` → `sdr.primary` still assigned;
  `sg rain-core -c 'rain-smoke devices'` agrees.
- Unassign `sdr.primary` → `Unassigned`. → `sudo sha256sum -c ~/phase2-before.sha256` is `OK` for `devices.json` (same document).

## 9. Displacement warning

Assign the CP2102 `dev_ccbc25d5a4210a5a` as `gps.primary`.
→ the confirmation says `gps.primary will be removed from u-blox 7 - GPS/GNSS Receiver (dev_74a462923d20f21e)` and shows the
class-mismatch warning checkbox, with **Cancel** as the default. Press Cancel → nothing changes; `devices.json` hash unchanged.

## 10. Core stop and start

- `sudo systemctl stop rain-core` → within 3 s `Core offline — retry in … s`, live fields `—`, assign disabled; no crash.
- `sudo systemctl start rain-core` → within 15 s `Core connected · 0.2.0` and the banner "rain-core restarted — please sign in again"; the console is Public.

## 11. Lock (D11)

- Sign in as `dragon`, open Devices, press **Ctrl+L** → **immediately** the `Locked — signed out` overlay, no device data or
  assign control visible, status strip `Public`. `sudo journalctl -u rain-core --since "-1 min" | grep -c 'logout user=dragon'` → `1`.
- Continue as public → counts only. Wrong password → still not signed in; right password → administrator.
- **Idle:** the idle-lock preference is file-based (no preferences screen in Phase 2). Close the console, then:
  ```bash
  f=~/.config/rain-console/console.toml; mkdir -p "${f%/*}"
  if grep -q '^idle_lock_minutes' "$f" 2>/dev/null; then sed -i 's/^idle_lock_minutes = .*/idle_lock_minutes = 1/' "$f"; else echo 'idle_lock_minutes = 1' >> "$f"; fi
  ```
  Relaunch, sign in as `dragon`, leave it untouched → locks within about 1 minute; the journal shows another `logout user=dragon`.
  Close the console and restore with the same command using `10`.
- **Unreachable core:** sign in as `dragon`, `sudo systemctl stop rain-core`, press Ctrl+L → locks immediately, no hang.
  `sudo systemctl start rain-core` → reconnects as Public; unlocking requires the password.

## 12. Rate limit

Wrong password 5 times → `too many attempts, retry in 30 s`, and Sign in is disabled (countdown). After 30 s the correct password works.

## 13. Keyboard only

Disconnect the mouse. Keyboard only: sign in (Ctrl+Shift+S), Devices (Ctrl+3), assign the RTL-SDR as `sdr.primary`
(Tab/arrows/Enter; Cancel is the default in confirmations), unassign it, lock (Ctrl+L). → everything reachable, focus ring
always visible. Reconnect the mouse.

## 14. Desktop and terminal stay reachable (§10.1)

In each state — (a) Public; (b) signed in as `dragon` with the Assign dialog open; (c) Locked; (d) fullscreen via F11 —
open the labwc application menu, start a terminal from it, switch between terminal and console with the desktop's window
switching, and run `systemctl is-active rain-core`. → works in every state; in (d) F11 returns to a normal window.

```bash
pkill -KILL -x rain-console
systemctl is-active rain-core
ls ~/.config/autostart 2>/dev/null | grep -c rain; grep -rls rain-console ~/.config/labwc 2>/dev/null | wc -l
```
→ the window disappears and panel, menu and terminal keep working; `active`; relaunch from the menu works; `0` and `0`.
Reboot and log in → the normal desktop appears and the console does **not** start by itself.

## 15. Boot independence

`sudo systemctl disable --now rain-core`, reboot → desktop boots normally; the console, launched from the menu, runs and
shows offline. `sudo systemctl enable --now rain-core` → it reconnects.

## 16. No secrets

```bash
read -rs PW            # dragon's password
sudo journalctl -b --no-pager | grep -cF -- "$PW"                                     # → 0
grep -rcF -- "$PW" ~/.config/rain-console ~/.local/state/rain-console | grep -v ':0$'  # → no output
unset PW
```
Repeat for `op`. Then `grep -rlw -e dragon -e op ~/.config/rain-console || echo "no username"` → `no username` (preferences hold no username).

## 17. Rollback check (optional)

```bash
cd ~/rain-phase2-dist && sudo bash ./rollback-0.1.1.sh
```
→ ends `OK: rain-core 0.1.1 running`; health `0.1.1`; the console shows `Core too old (0.1.x)`;
`gps.primary` intact (`sg rain-core -c 'rain-smoke devices'`); `sudo sha256sum -c ~/phase2-before.sha256` → 4 × OK.
`rain-core-admin` is gone with 0.2.0; `accounts.json` and `sessions.toml` stay (ignored by 0.1.1).
Re-apply: `sudo bash ./update-0.2.0.sh` → health `0.2.0`; step-0 hashes still match; accounts work again.

## 18. Sign-off: remove the smoke uid's administrator access (D6)

After every step that uses `rain-smoke devices` or `rain-smoke assign`. Only step 19 follows. This is the **only** step in
which the `auth.toml` hash changes, intentionally.
```bash
SMOKE_UID="$(id -u)"
sudo install -d -m 0700 /var/backups/rain-core
sudo cp -a /etc/rain/auth.toml /var/backups/rain-core/auth.toml.pre-phase2-signoff
sudo stat -c '%a %U:%G' /etc/rain/auth.toml                                   # note the value
sudo grep -cx "${SMOKE_UID} = \"administrator\"" /etc/rain/auth.toml          # → 1 (else stop and edit by hand)
sudo sed -i "/^${SMOKE_UID} = \"administrator\"\$/d" /etc/rain/auth.toml
sudo diff /var/backups/rain-core/auth.toml.pre-phase2-signoff /etc/rain/auth.toml
sudo stat -c '%a %U:%G' /etc/rain/auth.toml                                   # → same as noted
sudo systemctl restart rain-core                                              # auth.toml is read at start
sudo sha256sum /etc/rain/auth.toml | tee ~/phase2-auth-after-signoff.sha256
```
→ `diff` shows exactly one removed line `< <uid> = "administrator"`; mode and owner unchanged;
`sg rain-core -c 'rain-smoke health'` → ok; `sg rain-core -c 'rain-smoke devices'` → `forbidden`;
`sg rain-core -c 'rain-smoke assign dev_74a462923d20f21e'` → `forbidden`; in the console as `dragon`, assign and unassign
`sdr.primary` → both work; `sudo sha256sum -c ~/phase2-before.sha256` → `devices.json`, `core.toml`, unit `OK`,
**`auth.toml` FAILED, as intended**. Record the new hash. Undo of this step only:
`sudo cp -a /var/backups/rain-core/auth.toml.pre-phase2-signoff /etc/rain/auth.toml && sudo systemctl restart rain-core`.

## 19. Terminal recovery path after sign-off (D14) — rain-console not running

Use SSH or a text VT if available; otherwise a desktop terminal with the `env -u` form.
```bash
pkill -x rain-console; sleep 1
pgrep -u "$USER" -x rain-console || echo "rain-console not running"            # → rain-console not running
sudo sha256sum /var/lib/rain/devices.json | tee ~/step19-before.sha256
grep devices.json ~/phase2-before.sha256 | sudo sha256sum -c                     # → devices.json: OK
```
**(a) Unauthenticated detailed access is refused.**
```bash
sg rain-core -c 'rain-smoke devices'                                              # → forbidden
rain-core-admin probe --public > ~/public-after-signoff.jsonl
grep -cE 'dev_[0-9a-f]{16}|/dev/|by-id|usb-path:|gps\.primary|mesh\.primary|sdr\.primary|radio\.primary|smoke|"serial"|"devnode"|"alias"|"logical' ~/public-after-signoff.jsonl   # → 0
grep -c '"device.counts"\|"connected"' ~/public-after-signoff.jsonl                # → ≥ 1
rain-core-admin status --user op ; echo $?                                        # enter a WRONG password
```
→ `rain-core refused: invalid credentials`, `3`, no device data.

**(b) Inspection without rain-console.**
```bash
env -u WAYLAND_DISPLAY -u DISPLAY rain-core-admin report --user op ; echo $?      # op's password at the prompt
```
→ *(simulation format)* `== rain-core status ==` with `version: 0.2.0`, `service uid: 993`, `signed in: op · operator`,
`devices: N connected · M disconnected · T total`; `== devices ==` with `dev_74a462923d20f21e … connected devnode=/dev/ttyACM0 …
logical=gps.primary alias="smoke"` and the RTL-SDR and CP2102 lines with state and devnode; `== assignments ==`
`gps.primary → dev_74a462923d20f21e "smoke" Connected · …` and `mesh.primary/sdr.primary/radio.primary → Unassigned`;
`== events ==` lines with `seq=`; `rain-core log: journalctl -u rain-core -b`; exit `0`.
`sudo journalctl -u rain-core --since "-2 min" --no-pager | grep -cE 'login ok user=op|logout user=op'` → `2` or more.

**(c) Mutations need administrator authority and confirmation.**
```bash
rain-core-admin assign sdr.primary dev_ca4a208a9242de2c --alias sdr --user op --yes ; echo $?
```
→ `device.assign requires administrator (signed in as op · operator)`, `3`; `sudo sha256sum -c ~/step19-before.sha256` → OK.

Administrator round trip on a safe target (`sdr.primary` is unassigned; the RTL-SDR is used by no Phase 2 service):
1. `rain-core-admin assign sdr.primary dev_ca4a208a9242de2c --alias sdr --user dragon` — paste dragon's password; effects
   `sdr.primary → Blog V4 (dev_ca4a208a9242de2c)`, no displacement; type `yes` → `assigned: sdr.primary → dev_ca4a208a9242de2c alias "sdr"`.
2. `rain-core-admin assignments --user dragon` → `sdr.primary → dev_ca4a208a9242de2c "sdr" …`, `gps.primary` unchanged.
3. `rain-core-admin unassign sdr.primary --user dragon` → type `yes` → `sdr.primary` unassigned.

Ctrl-C logs out: `rain-core-admin assign sdr.primary dev_ca4a208a9242de2c --user dragon`, press **Ctrl-C** at `Type yes to continue:`
→ non-zero exit, nothing changes; `sudo journalctl -u rain-core --since "-1 min" --no-pager | grep -c 'logout user=dragon'` → `1`.

K1 kept, non-destructive:
- `rain-core-admin assign gps.primary dev_ccbc25d5a4210a5a --user dragon` → effects include
  `gps.primary will be removed from u-blox 7 - GPS/GNSS Receiver (dev_74a462923d20f21e)` and the class-mismatch WARNING;
  the prompt asks for `replace`. Press Enter → `cancelled; nothing was sent`, exit `5`.
- `rain-core-admin assign gps.primary dev_ccbc25d5a4210a5a --user dragon --yes ; echo $?` (no `--replace`) →
  **expected on 0.2.0:** `warnings shown; add --accept-warnings to proceed (nothing was sent)`, `3`.
  *Deviation from the §17.9 text:* the CP2102 is not classified for `gps.position`, so §10.2's rule ("a class-mismatch …
  warning additionally needs `--accept-warnings`. Without them, the CLI exits 3 and nothing is sent") applies before the
  request; the exit code (3) and "no change" are as specified. To see rain-core's own K1 refusal, also run
  `rain-core-admin assign gps.primary dev_ccbc25d5a4210a5a --user dragon --yes --accept-warnings ; echo $?` (still no `--replace`)
  → `rain-core refused: would-displace …`, `3`.
- `sudo sha256sum -c ~/step19-before.sha256` → OK. `rain-core-admin assignments --user op` → `gps.primary → dev_74a462923d20f21e "smoke"`.

**(d) Core down is reported, with no fallback.**
```bash
sudo systemctl stop rain-core
rain-core-admin status --user op ; echo $?
sudo systemctl start rain-core
rain-core-admin status --user op
```
→ `rain-core is not reachable at /run/rain/core.sock (…). Check: systemctl status rain-core; journalctl -u rain-core -b`,
`4`, **no password prompt**; after start, works again.

**(e) Break-glass reset.** `sudo rain-core-admin user passwd op` (new password, record it) → ok.
`rain-core-admin status --user op` → old password `invalid credentials`; new one works.
`sudo sha256sum -c ~/step19-before.sha256` → OK.

**(f) No secrets.** For each password used in this step: `read -rs PW; sudo journalctl -b --no-pager | grep -cF -- "$PW"; unset PW` → `0`.

---

## Completion (§18)

Phase 2 is accepted when step A, steps 0–16, 18 and 19 pass (17 passed or recorded as not performed, with the reason), the
console was launched manually throughout, no autostart/unit/labwc/display-manager change exists, and every deviation is in the
acceptance record. `devices.json`, `core.toml` and the unit keep their step-0 hashes; `auth.toml` changes only in step 18.

## Rollback at any time

- rain-core: `cd ~/rain-phase2-dist && sudo bash ./rollback-0.1.1.sh` (reinstalls the Pi-accepted 0.1.1 wheel; no file restore
  is needed; it refuses any other 0.1.1 wheel). Manual equivalent:
  `sudo systemctl stop rain-core && (cd / && sudo /usr/bin/python3 -m pip install --no-deps --no-index --break-system-packages ~/rain-phase2-dist/rain_core-0.1.1-py3-none-any.whl) && sudo systemctl start rain-core`.
- rain-console: `sudo bash ./uninstall-console.sh` (removes the wheel, menu entry and icon; leaves the Debian Qt packages and your
  `~/.config/rain-console`, which hold no secrets).
- Step 18 only: see the undo line in step 18.
- Backups made by the scripts: `/var/backups/rain-core/<UTC>-pre-0.2.0/` and `<UTC>-pre-rollback-0.1.1/` (0700, with SHA256SUMS).
