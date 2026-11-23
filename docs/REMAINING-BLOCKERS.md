# Remaining blockers before a public release (after Milestone B, updated 2026-11-23)

| # | Blocker | Needs | Blocks |
|---|---|---|---|
| 1 | **Licence decision.** GPL-3.0-or-later is not approved as final; the licensing audit report is waiting for review. | Maintainer decision | Publishing anything |
| 2 | **No package has been installed on a Raspberry Pi.** Packages are tested only in a Debian 13 arm64 chroot under qemu emulation on x86_64. | Approval + a spare SD card/Pi (clean-Pi test; never the working Pi) | Packages zip, real installer execution, offline bundle |
| 3 | Proposed versions task-mesh 0.3.2~alpha1, task-console 0.2.1~alpha1 and launcher 0.3.8 | **Approved** 2026-11-23 for packaging, isolated testing and volunteer packages only. Still not Pi-validated or published (see #7) | Volunteer bundle |
| 4 | **Placeholder metadata**: maintainer `TBD-maintainer-email` (lintian errors); `Source:` "upstream URL TBD" / "R.A.I.N. project …"; `example.invalid` in mesh/packaging/debian/copyright | Contact e-mail + repository URL (approval #2, #3) | Publishing debs |
| 5 | **Dependency pins**: read-only `dpkg-query` output from the development Pi was received 2026-11-23 (PySide6 6.8.2.1-4, numpy 2.2.4, scipy 1.15.3, libzim 3.6.0, gpsd 3.25, Direwolf 1.7, librtlsdr0 2.0.2 rather than librtlsdr2, SoapySDR modules installed individually, `soapysdr-module-all` not installed). Recorded in `packaging/debian/reference/pi-dpkg-baseline-20261122.txt`. Pins for the Milestone D offline bundle still need to be written from that output | Write pins from that baseline | Milestone D offline dependency bundle |
| 6 | **Installer is dry-run only**; real executor not written (sudo-in-terminal vs polkit undecided) | Approval #15 after #2 | Installer release |
| 7 | Launcher 0.3.8, task-mesh 0.3.2~alpha1, task-console 0.2.1~alpha1: approved 2026-11-23 for packaging and isolated testing only. Windows remains untested; no Windows support is claimed | Release approval after volunteer/clean-Pi tests; publication also needs the license decision | Installing on the working Pi, publishing |
| 8 | **Windows**: no Windows machine; Wine build only; launcher refuses to start under Wine (Wine reports an elevated admin); Core/Mesh have no Windows backends | Windows 11 test machine, Milestone E approval | Any Windows claim |
| 9 | Hardware acceptance pending: SDR 0.2.4 audio, Medical Reader fix (launcher 0.3.7), Maps 0.1.1 | Physical tests on the Pi | Marking these modules tested |
| 10 | No published apt repository / GitHub release; online install path has no source | Publishing approval | Online install |
| 11 | Radio design doc `docs/design/radio-phase5a/PACKAGING-AND-ROLLBACK.md` still plans `apt-get --no-download` with local .debs, which is broken in Debian 13's apt 3.0.4 | Update when Radio work resumes | Radio packaging |
