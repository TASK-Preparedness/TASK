# Dependencies

All T.A.S.K. packages are `Architecture: all` (pure Python). Runtime dependencies come from Debian 13
"trixie" (arm64), which is what the earlier phases target.

## Bundled in deps/arm64 (PARTIAL, honest statement)
These .debs were downloaded from deb.debian.org (trixie) for arm64. **This is NOT a complete offline
dependency closure.** It covers the new Phase 4C dependencies plus one level of their libraries. Packages
that are usually already on Raspberry Pi OS (libc6, libstdc++6, libusb-1.0-0, libasound2t64, libudev1,
PySide6 core/gui/widgets/network and the Qt6 base libraries that the launcher/maps/mesh 0.1/0.2 already need)
are not bundled. If one of those is missing and the Pi is offline, `apt` will report it and the install
stops cleanly. Nothing has been installed on the Pi to check this.

| package | version |
|---|---|
| direwolf | 1.7+dfsg-2+deb13u1 |
| libblas3 | 3.12.1-6 |
| libgfortran5 | 14.2.0-19 |
| libgps30t64 | 3.25-5+deb13u2 |
| libhamlib4t64 | 4.6.2-1+b1 |
| liblapack3 | 3.12.1-6 |
| libprotobuf32t64 | 3.21.12-11+deb13u1 |
| libqt6multimedia6 | 6.8.2-8 |
| librtlsdr0 | 2.0.2-2+b1 |
| libsoapysdr0.8 | 0.8.1-5+b2 |
| libyaml-0-2 | 0.2.5-2 |
| python3-decorator | 5.2.1-2 |
| python3-numpy-dev | 1:2.2.4+ds-1 |
| python3-numpy | 1:2.2.4+ds-1 |
| python3-protobuf | 3.21.12-11+deb13u1 |
| python3-pubsub | 4.0.3-7 |
| python3-pyside6.qtmultimedia | 6.8.2.1-4 |
| python3-pyudev | 0.24.3-1 |
| python3-scipy | 1.15.3-1 |
| python3-serial | 3.5-2 |
| python3-soapysdr | 0.8.1-5+b2 |
| python3-tabulate | 0.9.0-1 |
| python3-yaml | 6.0.2-1+b2 |
| soapysdr0.8-module-rtlsdr | 0.3.3-1+b4 |

## Per package (Depends fields)
* python3-task-comms: python3 (>= 3.11)
* task-core: python3, python3-yaml. Optional: none. Runs as the existing `rain-core` account.
* task-launcher: python3 (>= 3.13), PySide6 qtcore/qtgui/qtwidgets/qtnetwork/qtsvg/qtdbus
* task-maps: python3 (>= 3.13), PySide6 qtcore/qtgui/qtwidgets. Online tiles are optional; offline works.
* task-mesh: PySide6, python3-serial, pubsub, protobuf, pyudev, requests, tabulate, yaml, packaging,
  qt6-wayland, python3-task-comms. The meshtastic Python library is vendored (from the wheel).
* task-aprs: PySide6, python3-task-comms. **Direwolf is required for RF; it is Recommends (apt installs it by default; use `--no-install-recommends` to skip). Its postinst (read from the bundled trixie deb) only re-enables direwolf.service if it was enabled before, so a fresh install does not autostart it; still confirm with `systemctl is-enabled direwolf` after install**;
  task-aprs talks to it on 127.0.0.1 (AGW 8000) and never writes direwolf.conf.
* task-sdr: PySide6 incl. qtmultimedia, numpy, scipy, python3-soapysdr, soapysdr0.8-module-rtlsdr.
* task-console: PySide6.
