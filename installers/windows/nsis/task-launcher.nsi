; SPDX-License-Identifier: GPL-3.0-or-later
; SPDX-FileCopyrightText: 2026 Joshua Sturtz
; EXPERIMENTAL per-user installer for the PyInstaller "onedir" launcher build. UNVERIFIED on Windows.
; No administrator rights, no services, no auto-start, no driver installation. Uninstall keeps user
; data in %APPDATA%\TASK and %LOCALAPPDATA%\TASK.
; makensis -DVERSION=0.0.0 -DSRC=<path to dist\TASK-Launcher> -DOUT=<setup.exe> task-launcher.nsi
Unicode true
RequestExecutionLevel user
!ifndef VERSION
  !define VERSION "0.0.0-dev"
!endif
!ifndef SRC
  !error "SRC (PyInstaller dist\TASK-Launcher folder) is required"
!endif
!ifndef OUT
  !define OUT "TASK-Launcher-${VERSION}-experimental-setup.exe"
!endif
Name "T.A.S.K. Launcher (experimental) ${VERSION}"
OutFile "${OUT}"
InstallDir "$LOCALAPPDATA\Programs\TASK\Launcher"
SetCompressor /SOLID lzma
ShowInstDetails show
!include "MUI2.nsh"
!insertmacro MUI_PAGE_LICENSE "${SRC}\LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\TASK-Launcher"

Section "Launcher"
  SetOutPath "$INSTDIR"
  File /r "${SRC}\*.*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\T.A.S.K."
  CreateShortcut "$SMPROGRAMS\T.A.S.K.\T.A.S.K. Launcher.lnk" "$INSTDIR\TASK-Launcher.exe"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "T.A.S.K. Launcher (experimental)"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  Delete "$SMPROGRAMS\T.A.S.K.\T.A.S.K. Launcher.lnk"
  RMDir "$SMPROGRAMS\T.A.S.K."
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "${UNINST_KEY}"
  ; user data (%APPDATA%\TASK, %LOCALAPPDATA%\TASK) is intentionally kept
SectionEnd
