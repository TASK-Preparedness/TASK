# Missing sources, data and dependencies

Nothing listed here blocks the source tree; these block packaging, the offline bundle,
Windows builds or specific claims. Every collection step is read-only. **Run one command
at a time and share the output; nothing here changes the Pi.**

| # | Missing item | Needed for | How to collect safely |
|---|---|---|---|
| 1 | Exact Debian dependency versions on the Pi (Qt/PySide6, numpy/scipy, serial, protobuf, libzim, SoapySDR, gpsd, Direwolf, pulseaudio-utils, ffmpeg) | Pinned dependency manifest (Milestone B), offline bundle | `dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\n' python3 'python3-pyside6.*' python3-numpy python3-scipy python3-serial python3-protobuf python3-pubsub python3-pyudev python3-libzim python3-yaml 'soapysdr*' 'librtlsdr*' gpsd direwolf pulseaudio-utils ffmpeg` |
| 2 | Pi FFmpeg version and original OGA hash | Byte-level provenance of the alert WAV | `sha256sum /usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga` then `ffmpeg -version` (only if ffmpeg is installed) |
| 3 | Direwolf configuration actually in use and its listening ports | Radio/APRS packaging, Milestone B | (already requested) `ss -ltnp` while Direwolf runs; config path from `ps -o args= -C direwolf` |
| 4 | Validated arm64 `.deb` builds of every module at the installed versions | TASK-RaspberryPi-Packages | Build on the box (deterministic builders exist), then validate on a clean Debian 13 arm64 system (spare SD card / second Pi) — needs approval |
| 5 | A clean Debian 13 arm64 environment | Dependency closure for the offline bundle; package install/remove tests | Spare SD card on a Pi, or an emulated arm64 chroot on the build box (dependency resolution only; not a hardware test) |
| 6 | Hardware acceptance results: SDR 0.2.4, Medical Reader 0.3.7, Maps 0.1.1 (Joshua's 12 tests) | Promoting modules from experimental | Checklists were kept in a private engineering-history archive; they are not in this public tree |
| 7 | Windows 11 x64 test machine | Any Windows claim | Tester-owned PC or VM with USB pass-through |
| 8 | UV-PRO firmware version and whether a KISS setting exists | Any UV-PRO claim | Read from the radio's menu/app; no Bluetooth changes |
| 9 | Decisions in docs/APPROVALS-NEEDED.md | Release | Maintainer |

Not needed and intentionally **not** collected: `~/.config/task-mesh/radio-protocols.json`,
`/etc/task/auth.toml`, `sessions.toml`, APRS/GMRS configs, message databases, Bluetooth
pairing data, ZIM/MBTiles data.
