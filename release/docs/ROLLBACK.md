# Rollback

## task-core
`sudo task-core-migrate --rollback`: stops and disables task-core, removes `/etc/task/MIGRATED` and the
MIGRATED-TO-TASK note, restores the recorded mode of `/var/lib/rain`, verifies the legacy files against the
manifest, keeps the copies as `*.rolled-back-<ts>` for inspection, and re-enables/starts rain-core if it was
enabled/active before. Changes made while task-core ran are kept in the copies and reported, not merged.
Then optionally `sudo apt remove task-core task-core-compat` (files only; no data removed).
Last resort: the backup tarball in /var/backups (restore by hand only with Joshua).

## Apps
* task-launcher: `sudo apt install ./task-launcher_0.2.0_all.deb` (previous zip). Saved tile ids `task.*` are
  unknown to 0.2.0; expected (NOT tested) result: 0.2.0 shows its default tile order; the settings file is not deleted.
* task-mesh: `sudo apt remove task-mesh rain-mesh && sudo apt install ./rain-mesh_0.1.0_*.deb` (previous build).
  task-mesh copied (never moved) the rain-mesh data, so the old data is untouched.
* task-maps: `sudo apt install ./task-maps_0.1.0_all.deb`. 0.1.1 never changes the format of maps/*.mbtiles,
  imported files, jobs, waypoints or settings (schema 1; tested with 0.1.0's settings loader). The auto cache
  in `<data>/cache/` is ignored by 0.1.0 and can be deleted.
* task-aprs, task-sdr, python3-task-comms, task-console: `sudo apt remove <pkg>`; user data stays in ~/.config,
  ~/.local/share, ~/.local/state.
