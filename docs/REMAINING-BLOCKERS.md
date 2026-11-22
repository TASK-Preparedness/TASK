# Remaining blockers before a public release (after Milestone B, 2026-11-22)

| # | Blocker | Needs | Blocks |
|---|---|---|---|
| 1 | **Licence decision.** GPL-3.0-or-later is not approved as final; the licensing audit report is waiting for review. | Maintainer decision | Publishing anything |
| 2 | **No package has been installed on a Raspberry Pi.** Packages are tested only in a Debian 13 arm64 chroot under qemu emulation on x86_64. | Approval + a spare SD card/Pi (clean-Pi test; never the working Pi) | Packages zip, real installer execution, offline bundle |
| 3 | **Proposed versions** task-mesh 0.3.2~alpha1 and task-console 0.2.1~alpha1 | Maintainer approval | Bundle content |
| 4 | **Placeholder metadata**: maintainer `TBD-maintainer-email` (lintian errors); `Source:` "upstream URL TBD" / "R.A.I.N. project …"; `example.invalid` in mesh/packaging/debian/copyright | Contact e-mail + repository URL (approval #2, #3) | Publishing debs |
| 5 | **Dependency pins PENDING**: the Pi's versions of Qt/PySide6/numpy/libzim/etc. are unknown (the 2026-11-08 inventory covers T.A.S.K. packages only) | Read-only `dpkg-query` output from the Pi (command in packaging/debian/README.md) | Exact pins, Milestone D offline dependency bundle |
| 6 | **Installer is dry-run only**; real executor not written (sudo-in-terminal vs polkit undecided) | Approval #15 after #2 | Installer release |
| 7 | Launcher 0.3.8 (Windows portability patch + prefer `/usr/bin/task-console`) | Approval | Windows work, removing the stale-pip-copy risk |
| 8 | **Windows**: no Windows machine; Wine build only; launcher refuses to start under Wine (Wine reports an elevated admin); Core/Mesh have no Windows backends | Windows 11 test machine, Milestone E approval | Any Windows claim |
| 9 | Hardware acceptance pending: SDR 0.2.4 audio, Medical Reader fix (launcher 0.3.7), Maps 0.1.1 | Physical tests on the Pi | Marking these modules tested |
| 10 | No published apt repository / GitHub release; online install path has no source | Publishing approval | Online install |
| 11 | Radio design doc `docs/design/radio-phase5a/PACKAGING-AND-ROLLBACK.md` still plans `apt-get --no-download` with local .debs, which is broken in Debian 13's apt 3.0.4 | Update when Radio work resumes | Radio packaging |
