# Windows progress report (Milestone B, 2026-11-22)

**Bottom line: no Windows support is claimed. Nothing has run on Windows.** No Windows 11 machine or VM
was available. Wine 10.0 was available on the Debian 13 x86_64 build machine and was used for an
experimental build and smoke test. **Wine is not Windows**, so none of the results below are Windows test results.

## Done

| Item | Where | Status |
|---|---|---|
| task_platform config (TOML, atomic save, refuses unreadable writes) | `platform/task_platform/config.py` | implemented; Linux tests only |
| task_platform device discovery (known USB IDs → possible/likely/unknown; never opens ports) | `platform/task_platform/discovery.py` | implemented; Linux tests only |
| task_platform offline resources (read-only scan, SHA-256 manifest verify, safe names) | `platform/task_platform/resources.py` | implemented; Linux tests only |
| Windows serial listing via an injectable pyserial `comports` | `platform/task_platform/serial_ports.py` | implemented; listed 0 ports under Wine (no devices) |
| Capability table updated (no Windows entry marked verified; a test enforces this) | `platform/task_platform/capabilities.py` | done |
| Launcher portability patch (proposed launcher 0.3.8) | `installers/windows/patches/launcher-windows-prep.patch` | Not applied, so 0.3.7 stays byte-identical. With the patch applied, the launcher suite passes on Linux: 326 passed, 13 skipped. |
| PyInstaller spec, build script (stages, `git apply --check`, refuses off Windows) | `installers/windows/` | done |
| NSIS per-user installer script; WiX per-user MSI skeleton; evaluation | `installers/windows/{nsis,wix,README.md}` | `makensis` 3.11 and `wixl` 0.106 compile them with a dummy payload |
| Simulated-Windows import check (Linux CPython, POSIX `os` removed) | `tools/simulate_windows_launcher.py` | 0.3.7: `app` fails to import (`os.geteuid`). Patched: 0 failures, MainWindow builds. |
| Windows CPython under Wine smoke | `tools/wine_smoke.py` | CPython 3.12.10 win-amd64 + PySide6 6.8.2.1: 0 import failures (launcher + task_platform); MainWindow builds offscreen; `%APPDATA%`/`%LOCALAPPDATA%`/`%TEMP%` paths correct |
| PyInstaller 6.11.1 onedir build under Wine | build machine only | Builds: 92 MB folder, 38 MB zip, sha256 `23847d6b…2270`. Over the 25 MB limit, so it is **not shipped**. |

## Findings
1. Running the frozen exe under Wine, the launcher refuses with "must not run as root". Wine's default
   user is an elevated administrator (`IsUserAnAdmin()` is True). On real Windows with UAC, an unelevated
   admin should get False. This must be checked on Windows 11 before anything else.
2. Bundled `apps.d` entries name Linux commands (`task-console`, `task-mesh`, …). On Windows their
   tiles would point at programs that do not exist. A Windows apps.d set is needed (Milestone E).
3. Wine teardown printed a `CloseHandle` error from `subprocess.__del__` (exit 9 after all checks passed). This is probably Wine; unverified.
4. Core (Unix socket), Mesh service (systemd user unit), D-Bus notifications and `paplay` have no Windows backends yet (see WINDOWS.md).

## Not done / needs
* A native Windows 11 x64 build and run as an unelevated user; NSIS install/uninstall on Windows.
* Approval of launcher 0.3.8 (this patch + the console path preference), a code-signing decision, and CI after publishing is approved.
