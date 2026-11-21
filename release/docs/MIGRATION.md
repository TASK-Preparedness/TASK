# task-core migration (rain-core 0.2.1 → task-core 0.3.0)

**NOT AUTHORIZED YET.** Joshua approved development only. Do not run any of this on the Pi until he
approves installation/migration separately. Never edit /etc/rain/*.toml, /var/lib/rain/devices.json or
assignments by hand. Do not run the Phase 1/2 installers. No `apt autoremove`.

What `task-core-migrate` does (tested in a sandbox only: 18 automated tests including power cuts at 9 points,
rollback and mutual exclusion):
1. preflight (root, rain-core state, free space, no previous finished migration)
2. stop rain-core (if active)
3. backup `/etc/rain`, `/var/lib/rain` and the unit file to `/var/backups/task-core-migration-<ts>.tar.gz` (0600)
4. **copy** (never move) `/etc/rain` → `/etc/task`, `/var/lib/rain` → `/var/lib/task` (staging + fsync)
5. verify every file (sha256 manifest + JSON/TOML parse); abort if the legacy files changed meanwhile
6. rewrite only paths in the copied `/etc/task/core.toml` (/run/rain→/run/task, /var/lib/rain→/var/lib/task,
   /usr/lib/rain→/usr/lib/task-core, /etc/rain→/etc/task)
7. promote staging, `systemctl disable rain-core` (the unit file stays; `mask` is not possible for a unit in
   /etc/systemd/system), write `/var/lib/rain/MIGRATED-TO-TASK`, chmod 0550 `/var/lib/rain` (old mode recorded)
8. write `/etc/task/MIGRATED` (task-core.service has `ConditionPathExists=/etc/task/MIGRATED`)

A journal (`/var/lib/task/.migrate-journal.json`) makes an interrupted run resumable: just run it again.

Steps (when approved; Joshua types any passwords himself):
```
sudo apt install ./python3-task-comms_0.3.0_all.deb ./task-core_0.3.0_all.deb ./task-core-compat_0.3.0_all.deb
systemctl is-active rain-core          # still active: installing changes nothing
sudo task-core-migrate --dry-run
sudo task-core-migrate
sudo systemctl daemon-reload && sudo systemctl enable --now task-core
task-core-admin status                 # health, device counts, assignments same as before
```
Account/group rename (M4) and legacy cleanup (M5) are **separate future approvals**. The service still runs as
the `rain-core` account; the socket `/run/task/core.sock` has a compat link `/run/rain/core.sock`.

Note: task-core 0.3.0 reports runtime/protocol version **0.2.1** (unchanged code; the Phase 1 golden tests pin
it). The deb version 0.3.0 marks the rename + migration tool.
