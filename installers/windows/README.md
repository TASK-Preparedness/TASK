# Windows build (EXPERIMENTAL, not supported)

**No Windows support is claimed.** Nothing here has run on Windows. An experimental launcher build
was produced with Windows CPython **under Wine** on Linux. Wine is not Windows, so that build is
**UNTESTED** and must not be published or presented as a release.

| File | Purpose |
|---|---|
| (merged) launcher 0.3.8 | The portability changes are part of `launcher/` since 0.3.8 (approved 2026-11-23). They touch paths (`%APPDATA%`/`%LOCALAPPDATA%`/`%PROGRAMDATA%` under `TASK`), the privilege check (`IsUserAnAdmin` instead of `os.geteuid`), temp/runtime names (no `/tmp`, no `os.getuid`) and the manifest owner check. Linux behaviour is unchanged: the launcher suite passes (326 passed, 13 skipped). |
| `build_windows.py` | Stages git-tracked `launcher/` (refuses a launcher without the 0.3.8 changes) + `platform/` sources, runs PyInstaller (`task-launcher.spec`, onedir), and optionally NSIS. It refuses to run PyInstaller off Windows. `--use-stage` reuses a stage made with `--stage-only`. |
| `task-launcher.spec` | PyInstaller spec: windowed, no UAC elevation, no QtWebEngine; bundles `apps.d`, LICENSE and THIRD_PARTY_NOTICES. |
| `nsis/task-launcher.nsi` | Per-user installer (`RequestExecutionLevel user`, `%LOCALAPPDATA%\Programs\TASK\Launcher`, HKCU uninstall entry). No services, no auto-start, no drivers. Uninstall keeps `%APPDATA%\TASK` and `%LOCALAPPDATA%\TASK`. |
| `wix/task-launcher.wxs` | Per-user MSI skeleton for managed deployment. The file list is harvested at build time. |
| `tools/simulate_windows_launcher.py` | Linux CPython with POSIX `os` functions removed and `sys.platform = "win32"`. Catches POSIX assumptions only. |
| `tools/wine_smoke.py` | Windows CPython (e.g. under Wine): imports every launcher + task_platform module and builds the main window offscreen. |
| `tests/test_windows_prep.py` | Stage contains the portable launcher; launcher >= 0.3.8; simulated import; build refuses off Windows; NSIS/WiX scripts compile with a dummy payload (`makensis`, `wixl`). |

## NSIS vs WiX

| | NSIS 3.11 | WiX (v3 schema; checked with msitools `wixl` 0.106) |
|---|---|---|
| Licence | zlib/libpng | MS-RL (WiX); LGPL (msitools) |
| Output | `.exe` installer + uninstaller | `.msi` (Windows Installer: repair, managed deployment, GPO/Intune) |
| Per-user install | yes (`RequestExecutionLevel user`) | yes (`InstallScope="perUser"`) |
| Build on Linux | yes (`makensis`, Debian package) | partly: `wixl` covers a subset; real WiX needs Windows/.NET |
| Upgrade/uninstall | scripted by us | built-in MajorUpgrade, repair, rollback |
| Recommendation | **first experimental installer** (simple, buildable in CI on any OS) | later, when managed deployment is needed |

Inno Setup was not chosen because its licence is not OSI-approved.

## Results on the build machine (Debian 13 x86_64, 2026-11-22)

* Wine 10.0 + Windows CPython 3.12.10 (python.org NuGet package) + PySide6-Essentials 6.8.2.1 +
  PyInstaller 6.11.1 + pyserial 3.5. These were installed into a scratch Wine prefix, not into the system Python.
* `wine_smoke.py`: 0 import failures across launcher and task_platform; `MainWindow` builds offscreen;
  paths resolve to `C:\users\<user>\AppData\Roaming\TASK\task-launcher` and `…\Local\TASK\task-launcher`,
  instance file under `%TEMP%`. Exit code 9 at interpreter teardown (Wine `CloseHandle` error in
  `subprocess.__del__`), after all checks had passed.
* PyInstaller onedir build: succeeded (92 MB folder, 38 MB zip). This exceeds the 25 MB deliverable limit,
  so it is kept on the build machine only and is **not** part of the release outputs.
* Running the frozen `.exe` under Wine: it **refused to start** with "task-launcher must not run as root".
  Wine's default user reports as an elevated administrator (`IsUserAnAdmin() == True`). On real Windows
  with UAC, an unelevated administrator should report False. This is unverified; test it on Windows 11 first.
* `makensis` compiles the NSIS script and `wixl` builds the MSI skeleton, both with a dummy payload only.

## Before any Windows claim
A Windows 11 x64 machine (or VM): run the build natively, start the launcher as an unelevated user,
install and uninstall with NSIS, check the paths. Also needed: maintainer approval of launcher 0.3.8
(done 2026-11-23), code-signing decision, and CI (GitHub Actions `windows-latest`) after publication is approved.
