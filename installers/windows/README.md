# Windows installer (planned)

Nothing here builds yet. Plan (see ../../WINDOWS.md): PyInstaller "onedir" build of the
shared PySide6 apps, wrapped in a per-user NSIS installer (or WiX MSI for managed
deployment); no administrator rights, no auto-start, uninstall keeps user data in
`%APPDATA%\TASK` / `%LOCALAPPDATA%\TASK` unless the user chooses otherwise.
Requires a Windows 11 x64 test machine before any build is published.
