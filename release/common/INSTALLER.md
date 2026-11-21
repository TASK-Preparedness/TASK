# T.A.S.K. hardened installer (used by every corrected release zip)

Run everything as the **desktop user** (not root). Only the apt step asks for sudo.

| Script | Changes the system? | Purpose |
|---|---|---|
| `./preflight.sh` | **No** | All checks. Exit 0 = ready (warnings possible), 1 = at least one FAIL |
| `./install.sh` | No (check mode) | Runs preflight and prints the plan |
| `./install.sh --install` | Yes, after typed confirmation | preflight → type `INSTALL <release-id>` → backup → one `sudo apt-get install --no-remove <debs>` → version check |
| `~/task-backups/<id>-<time>/rollback.sh <that dir> [--restore-data]` | Yes, after typed confirmation | Explicit rollback from the backup (see below) |

## Preflight checks
| Check | Result |
|---|---|
| `SHA256SUMS` of the zip | FAIL on mismatch |
| **Host platform** (first, in preflight, install AND rollback; shared `tg_require_host`) | **Hard FAIL, exit 1**, before anything else runs (see below) |
| Every deb is `Architecture: all` or `arm64` | FAIL otherwise |
| Installed version newer than the zip | FAIL (never downgrades) |
| Required T.A.S.K. packages and minimum versions | FAIL if missing or too old |
| A rollback package exists in the zip for every currently installed version | FAIL otherwise |
| Programs that must be closed (e.g. `task_sdr`, `task_resources`) | FAIL while running |
| Programs to restart afterwards (`task_launcher`) | WARN |
| SoapySDR (SDR releases): `python3-soapysdr` marked *automatic* | WARN with the `apt-mark manual` command to run **yourself**. Never run automatically |
| Release checks (Medical): each Resources DB is copied consistently into a private temp dir and `integrity_check` is run on the copy | FAIL on error; the source is never modified |
| `apt-get -s -o Debug::NoLocking=1 install --no-remove <debs>` | FAIL on nonzero exit, any `Remv`/`Purg` line, `E:` / unmet / broken, any downgrade |

## Host platform rule (hard requirement)
Accepted only when **all** hold:
1. `/usr/bin/dpkg --print-architecture` prints exactly `arm64`.
2. `/etc/os-release` exists, is a readable regular file ≤ 64 KiB, and parses strictly. Allowed lines: blank, `#` comment, or `KEY=VALUE` where the value is unquoted safe characters, a `"double"` string (no unescaped `"`, `$`, `` ` ``, `\`) or a `'single'` string. Duplicate keys, any other line, or an empty file mean **malformed: rejected**. The file is parsed, never sourced or executed.
3. `ID=debian`, `VERSION_ID=13` and `VERSION_CODENAME=trixie`.

**Raspberry Pi OS:** 64-bit Raspberry Pi OS (trixie) ships Debian's os-release unchanged (`ID=debian`, `VERSION_ID="13"`, `VERSION_CODENAME=trixie`, `DEBIAN_VERSION_FULL=13.x`) and is accepted by rule 3 as-is. 32-bit Raspberry Pi OS reports `ID=raspbian`, `ID_LIKE=debian` on armhf and is rejected (architecture and ID). `ID_LIKE` is **never** used as a fallback, because Ubuntu and other derivatives also declare `ID_LIKE=debian`. Evidence: os-release contents posted by users from real systems (forums.raspberrypi.com topic 395293; raspberrypi.com downloads page lists the 64-bit image as "Debian version 13 (trixie)"). That is **not an official specification**, so Pi checklist step 0 records the real file before anything else.

Each failure message says what was **found**, what was **expected**, and **why**. When rejected: no further check, no apt call (not even `-s`), no backup, no file, configuration or service change.

## Threat model and how tests work without a bypass
* The scripts contain **no override of any kind**: no test-mode variable, no os-release path option, no fixture marker. Tool paths (`/usr/bin/dpkg` …) and `/etc/os-release` are fixed constants.
* Each entry script starts with a prologue that re-runs itself as `env -i HOME TERM LC_ALL=C PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p` unless the environment is already exactly that. `bash -p` ignores `BASH_ENV`/`ENV` and imported functions; `env -i` drops `LD_PRELOAD`, `APT_CONFIG`, `DPKG_*`, `PYTHON*`, `PATH` changes and everything else. Python helpers run with `python3 -I`.
* Proven by `test_i23` on a **real** run on the x86_64 build box (no namespace): 8 vectors × 2 invocation styles (`./script` and `bash script`) for preflight and install. The vectors: old test variables, a fake `dpkg` first on PATH, `BASH_ENV`/`ENV` redefining the checks, plain variables (`DPKG`, `OS_RELEASE`, `TG_REQ_ARCH`, `SHELLOPTS`, …), exported functions, `LD_PRELOAD`, `APT_CONFIG`/`DPKG_ROOT`, and fixture-marker files. Every one is rejected with "found 'amd64', expected 'arm64'"; nothing is changed.
* Out of scope: someone who edits the scripts or runs their own code as the user could do anything anyway. `SHA256SUMS` detects edited files.
* **Tests** run the unmodified scripts inside a private **user + mount namespace** (`unshare --user --map-root-user --mount`). Fixture files (fake `dpkg`, `apt-get`, `dpkg-query`, `apt-mark`, `sudo`, `id`, `pgrep`, and an os-release) are bind-mounted over the real `/usr/bin/<tool>` and `/etc/os-release` (or an empty tmpfs over `/etc` for "missing"). Those mounts exist only inside that throw-away namespace. This needs no production code path, so it cannot be enabled on a real run.

## Backup (`~/task-backups/<release-id>-<YYYYmmdd-HHMMSS>/`, mode 0700)
`versions-before.txt`, `rollback-plan.txt`, `rollback-debs/` (sha256-verified copies, with their own SHA256SUMS), `home/` (settings), `sqlite/` (one consistent file per DB, from the SQLite backup API, plus `live-set-before.txt` with size and sha256 of db/-wal/-shm), `dpkg-state/` (`dpkg -l`, `dpkg-query` TSV, `apt-mark showmanual/showauto`, architecture, os-release), plus copies of `rollback.sh`, `task-guard.sh`, `release.conf` and `tools/`. Rollback therefore works even if the zip is gone.

## Rollback
1. Reads `versions-before.txt`. Packages that were **not installed** before are left installed. Removal is your decision, e.g. `sudo apt-get remove task-sdr`, and is never done here.
2. Verifies the sha256 of each rollback deb.
3. Simulates. Only the packages being rolled back may downgrade, and nothing may be removed.
4. You type `ROLLBACK <release-id>`.
5. `sudo apt-get install --no-remove --allow-downgrades <rollback debs>`.
6. `--restore-data`: current settings dirs are **moved** to `<name>.pre-rollback-<time>`. Each DB's db/-wal/-shm set is **moved together** into `pre-rollback-<time>/`, then the backup is copied back. Nothing is deleted.

## Never
autoremove · remove/purge · `apt-mark` changes · `-y` · starting or enabling services · touching `/etc/rain/*`, `/var/lib/rain/*`, device, GPS, SDR, radio or Meshtastic configuration · firmware · transmitting.

## Tests
`release/common/tests/test_installers.py` (105 tests) runs these exact scripts in the namespace fixture described above, with real dummy debs.
* **Package and apt checks:** simulation exit 1/100, Remv, Purg, downgrade (installed version and Inst line), broken and missing deps, wrong deb arch, SHA mismatch.
* **Host platform:** arm64 + Debian 13 / 64-bit Raspberry Pi OS accepted. Rejected: amd64, armhf, i386, riscv64, a failing dpkg; Debian 12/14/testing, Ubuntu, Fedora, 32-bit Raspbian, ID_LIKE-only, wrong or missing codename, empty, garbage, unterminated quote, command substitution, duplicate key, binary, missing file. Each rejection is checked in preflight, install and rollback, with no apt call, backup or file change.
* **Other:** preflight/install agreement; environment-bypass attempts on a real run; wrong or near-miss confirmations; running program; missing rollback deb; a full install with all backup contents checked; a rollback that refuses Remv or foreign downgrades and then restores data by moving it aside; never removing a package absent before; SoapySDR warn without apt-mark; static safety greps (including "no override mechanism exists") of all scripts and release.conf files.
