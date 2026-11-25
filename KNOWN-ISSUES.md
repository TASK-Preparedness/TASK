# Known issues

Updated 2026-11-24 (public alpha preparation). Hardware status is in HARDWARE.md, test results in TESTING.md.

> **EXPERIMENTAL ALPHA — NOT VALIDATED ON A PHYSICAL RASPBERRY PI.**

## Resolved in Milestone B

### Mesh AT-15 test failure (`test_at15_sigkill_loop_quick_check_ok`): test bug, not a Mesh bug
* **Symptom:** every SQLite `quick_check` passed, but row counts dropped between restarts
  (e.g. 18000 → 9200). Failed 2/2 on 2026-11-21.
* **Cause:** the test wrote node/observation rows with fixed timestamps from about 2026-09-21. Each
  writer restart opens the database, and the start-up retention prune (`node_observations_days = 30`)
  deletes observations older than 30 days. From about 2026-10-21 onwards, the test's own rows were
  older than the retention window, so they were pruned on the next start. The test started failing
  on the calendar, not because of a code change. The Mesh retention behaviour is correct and was **not changed**.
* **Fix:** the test now uses a frozen clock. Rows are stamped `REF + i`, and the writer and
  `open_database` get `now=REF`, so the result does not depend on the date. A new regression test,
  `test_at15_clock_regression_retention_unchanged`, shows retention still keeps rows at 29 days and
  prunes them at 31 days. The old test, run unchanged, still fails, which confirms the cause.

### Console `test_75_installer_footprint`: Debian 13 pip installs into `/usr/local/local`
* **Cause:** Debian's python3 uses the `posix_local` sysconfig scheme, which adds `/local` to any
  prefix. `pip install --prefix /usr/local` therefore lands in `/usr/local/local/...`. The test used
  `--prefix /usr/local`; `install-console.sh` itself passes no `--prefix` and was not affected.
* **Fix:** the test uses `--root` without `--prefix`, matching the script. `install-console.sh` is now
  marked DEVELOPER/LEGACY ONLY, and it **refuses to run when the task-console .deb is installed**
  (override: `TASK_CONSOLE_ALLOW_SHADOW=1`), so it cannot shadow `/usr/bin/task-console` with
  `/usr/local/bin/task-console`. The .deb is the only supported install path. The installed
  task-console 0.2.0 .deb, task-core 0.3.0 and launcher 0.3.7 are unaffected.

## Open

| Area | Issue | Status |
|---|---|---|
| task-console 0.2.0 packaging | Imports `PySide6.QtNetwork` but does not depend on `python3-pyside6.qtnetwork`. It fails when installed without task-launcher (found in the arm64 chroot). | Fixed in 0.2.1~alpha1 (approved 2026-11-23 for packaging and isolated testing; not Pi-validated) |
| Launcher tile (Devices) | 0.3.7 tries `/usr/local/bin/task-console` before `/usr/bin/task-console`, so a stale pip copy wins. | Fixed in launcher 0.3.8 (prefers `/usr/bin`); approved 2026-11-23 for packaging and isolated testing; not Pi-validated. The installer warns about shadowing copies. |
| task-mesh 0.3.1 | The installed notifier differs from the 0.3.1 package (the maintained audible alert). `dpkg --verify` reports it. | 0.3.2~alpha1 ships it (approved 2026-11-23 for packaging and isolated testing; not Pi-validated) |
| Packaging metadata | The frozen alpha `.deb` files still have the placeholder maintainer field `TBD-maintainer-email` (not a contact address), plus `Source:` URLs TBD, which lintian flags. User-facing contact is GitHub Issues and private vulnerability reporting only. | Left unchanged so volunteer-test SHA-256 checksums stay valid; a later approved rebuild can fix the metadata |
| Launcher on Windows | 0.3.7 did not import on Windows (`os.geteuid`); fixed in 0.3.8. Under Wine the frozen build refuses to start because Wine reports an elevated admin. | Untested on Windows; no Windows support is claimed |
| task-mesh Recommends | `task-mesh` 0.3.2~alpha1 newly Recommends `pulseaudio-utils` (for `paplay`). A default `apt` install/upgrade on a system that does not have it will want to download `pulseaudio-utils` and `libpulsedsp`. The development Pi already has pulseaudio-utils 17.0+dfsg1-2+rpt1. Offline upgrades without that package need `--no-install-recommends` or a local copy. | Experimental package; not Pi-validated. Documented in INSTALL.md and docs/VOLUNTEER-TESTING.md |
| Installer | Dry run only. It has never run on a real Pi. | By design until a clean-Pi test is approved |
| Hardware acceptance | SDR 0.2.4 audio, Medical Reader fix (launcher 0.3.7), Maps 0.1.1 | Pending physical tests |
