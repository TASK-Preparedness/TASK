# Testing

> **EXPERIMENTAL ALPHA — NOT VALIDATED ON A PHYSICAL RASPBERRY PI.**
> Figures below are automated tests and an emulated arm64 chroot on an
> x86_64 build machine, unless a row explicitly says otherwise.

## How to run

```bash
scripts/run-all-tests.sh            # every suite, Debian system Python, offscreen Qt, no network
```
Logs and `SUMMARY.txt` go to `build/test-logs/`. Core `test_77` (historical R.A.I.N.
update path) needs `RAIN_020_WHEEL=<path to rain_core-0.2.0-py3-none-any.whl>`
(SHA-256 `253572c5e3f7b09012292b451460f2cae8a97ad529f20780c05174790b892bad`); without it, it fails with a clear message.

Requirements: see CONTRIBUTING.md (Debian 13 `python3-*` packages incl. PySide6 6.8).

## Recorded results — 2026-11-22 (America/New_York), Milestone B (branch `milestone-b`)

Same build machine as below: Debian 13 **x86_64**, Python 3.13.5, PySide6 6.8.2.1, offscreen Qt.
`scripts/run-all-tests.sh` (log: `SUMMARY.txt` in the Milestone B test-results zip):

| Suite | Result |
|---|---|
| core | 178 passed |
| console | 53 passed (was 50 passed / 1 failed; +2 new tests) |
| comms | 29 passed |
| aprs | 35 passed |
| launcher | 326 passed, 13 skipped |
| maps | 132 passed |
| resources | 154 passed, 1 skipped |
| sdr | 305 passed, 1 skipped |
| release/common | 113 passed |
| platform | 20 passed |
| installers/raspberry-pi (simulation) | 83 passed |
| installers/windows (Linux-side checks, NOT a Windows test) | 7 passed |
| mesh | 370 passed (was 368 / 1 failed; +1 new test) |
| **Total** | **1,805 passed, 0 failed, 15 skipped** |

AT-15 file (`mesh/tests/integration/test_db_crash_safety.py`, 2 tests) was also run 5 times in a row: 5/5 passed.
Both earlier failures are explained in KNOWN-ISSUES.md.

### Packaging tests (not part of run-all-tests.sh; need root, qemu-user-static, mmdebstrap)
* `packaging/debian/build_debs.py`: two builds give identical SHA256SUMS. Eight packages are byte-identical
  to the delivered debs, and the verification builds of mesh 0.3.1 and console 0.2.0 are byte-identical too.
* `packaging/debian/verify_debs.py`: every payload file equals the Pi's installed file, apart from the expected changelog differences.
* `packaging/debian/chroot_test.py`: Debian 13 **arm64 chroot under qemu-user emulation** on the
  x86_64 machine. Results are in `chroot-results.json` in the debs zip. This is **not** a Raspberry Pi test.

## Recorded results — 2026-11-21 (America/New_York), commit of this tree

Build/test machine: Debian GNU/Linux 13 (trixie) **x86_64**, Python 3.13.5, PySide6 6.8.2.1, pytest 8.3.5, pytest-qt 4.4.0 (all Debian
packages), `QT_QPA_PLATFORM=offscreen`. **Not** a Raspberry Pi and
**not** arm64: these are automated software tests only.

| Suite | Result |
|---|---|
| core (task-core, migration, R.A.I.N. compat) | 178 passed (with `RAIN_020_WHEEL` supplied) |
| console (Devices) | 50 passed, **1 failed** |
| comms | 29 passed |
| aprs | 35 passed |
| launcher | 326 passed, 13 skipped |
| maps | 132 passed |
| resources | 154 passed, 1 skipped |
| sdr | 305 passed, 1 skipped |
| release/common (bash installer framework) | 113 passed |
| platform (new) | 10 passed |
| installers/raspberry-pi (new, simulation) | 37 passed |
| mesh | 368 passed, **1 failed** |
| **Total** | **1,737 passed, 2 failed, 15 skipped** |

### Failures (not hidden, not fixed in this milestone)
1. `console/tests/test_console_install.py::test_75_installer_footprint` — the legacy
   pip-based `install-console.sh` path installs under `usr/local/local/…` with Debian 13's pip
   when `--prefix /usr/local` is used. Affects only the legacy pip installer; task-console is
   installed from its `.deb` on the Pi. Needs a fix or retirement of the legacy script.
2. `mesh/tests/integration/test_db_crash_safety.py::test_at15_sigkill_loop_quick_check_ok` —
   every SQLite `quick_check` inside the test passed, but the test's final assertion that row
   counts never decrease failed (first count 18000, then 9200). Likely cause (unconfirmed):
   on this fast machine the writer inserts enough rows for the start-up retention prune to
   delete some on the next start. Failed in 2 of 2 runs here. Needs investigation.

### Skips
Render-to-file tests skip unless `TL_RENDER_DIR` is set; SoapySDR hardware test skips without
SoapySDR; one Qt PDF test skips without QtPdf.

### Changes made to tests during consolidation
* `release/common/tests/test_installers.py`: expected release-config count 5 → 6 (SDR 0.2.4 merge).
* `mesh/tools/run_tests_debian.sh`: extracts all four pinned vendored wheels; previously two
  MeshCore tests failed with `No module named 'meshcore'`.
* Ten scripts gained SPDX headers (core `test_52` failed before on an engineering-history script).

### Earlier run of the unmodified merged tree (same machine, same day)
core 176 passed / 2 failed (SPDX header; missing RAIN wheel), console 1 failed (same as above),
launcher 325 passed / 1 failed (missing `python3-pyside6.qtdbus` on the box, then installed),
resources 153 passed, release/common 1 failed (config count), mesh 364 passed / 3 failed
(2 × missing meshcore in the test runner, at15).

## Not tested (requires physical hardware or other environments)
UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST:
* The installer on any real Raspberry Pi (Pi 5, 4, 3, Zero 2 W); its detection on real `/proc`/`/sys`.
* Installing, upgrading or removing any package built from this tree **on a Raspberry Pi**
  (done only in an emulated arm64 chroot, see above).
* Offline installation.
* Any Windows behaviour (only Wine and a simulated-Windows import check were used).
* Radios, GPS, SDR and Bluetooth with code from this tree (the same code is installed on the
  development Pi; its hardware status is in HARDWARE.md).
