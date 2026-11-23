# Contributing to T.A.S.K.

Thank you. T.A.S.K. is built by and for radio operators, emergency volunteers,
developers and everyday people. Every contribution is welcome: testing on your
hardware, bug reports, documentation, translations and code.

This tree is an **experimental alpha**. The public packages have **not** been
validated on a physical Raspberry Pi. Please say clearly what you tested, on
what hardware, and what you did not test.

## Ground rules

* Be kind — see the [Code of Conduct](CODE_OF_CONDUCT.md).
* Never commit secrets, callsign databases, personal data, device serial
  numbers, your own config files or machine-specific paths.
* Never add code that transmits on a radio without an explicit operator
  action, starts services automatically, flashes firmware without explicit
  confirmation, or uses `shell=True`.
* Report results honestly.
* A project-wide license has **not** been approved yet (see [LICENSE](LICENSE)).
  Do not add new SPDX license identifiers that imply a final project license
  has been chosen. Until the owner decides, leave existing headers as they
  are, and discuss new files on the pull request. By contributing you agree
  that the copyright holder may apply the finally approved project license
  to your contribution; third-party code must keep its own license and
  notices.

## Volunteer testers: how to report problems

1. Read [SAFETY.md](SAFETY.md) and [INSTALL.md](INSTALL.md). Use a spare SD
   card. Do not transmit unless you are licensed and you intend to.
2. Verify SHA-256 checksums before installing anything.
3. Prefer the GitHub issue templates (see also [SUPPORT.md](SUPPORT.md)):
   * [Bug report](.github/ISSUE_TEMPLATE/bug_report.yml) — something is wrong
   * [Volunteer test report](.github/ISSUE_TEMPLATE/test_report.yml) — pass,
     fail, skip, or blocked
   * [Hardware compatibility](.github/ISSUE_TEMPLATE/hardware_report.yml)
   * [Installation problem](.github/ISSUE_TEMPLATE/installation_problem.yml)
4. Include, when you can:
   * Pi model and revision (`cat /proc/device-tree/model`;
     `grep Revision /proc/cpuinfo`)
   * OS and architecture (`cat /etc/os-release`; `dpkg --print-architecture`)
   * Package versions
     (`dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\n' 'task-*' python3-task-comms`)
   * Steps to reproduce, expected vs actual result, and redacted logs
5. Redact callsigns, locations, GPS tracks, messages, serial numbers,
   passwords, and personal paths before posting.
6. Please do not use a public issue for security or unexpected-transmit
   reports — see [SECURITY.md](SECURITY.md).

## Development setup (Debian 13 trixie)

```
sudo apt install python3-pytest python3-pytestqt python3-yaml python3-setuptools \
  python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets python3-pyside6.qtnetwork \
  python3-pyside6.qttest python3-pyside6.qtsvg python3-pyside6.qtdbus python3-pyside6.qtmultimedia \
  python3-pyside6.qtwebenginewidgets python3-numpy python3-scipy python3-serial python3-protobuf \
  python3-pubsub python3-pyudev python3-libzim python3-tabulate python3-requests
```

Use the system interpreter `/usr/bin/python3` (or an isolated venv). Do not
`pip install` into the system Python.

## Running tests

See [TESTING.md](TESTING.md). In short: `./scripts/run-all-tests.sh`.

## Building Debian packages

Existing builders (deterministic `dpkg-deb`, no network):
`launcher/packaging/build_deb.py`, `maps/packaging/build_deb.py`,
`resources/packaging/build_deb.py`, `mesh/packaging/build-deb.sh`,
`release/build_release.py` (core, compat, comms, console, aprs) and
`release/corrections/build_sdr_024.py`. The Milestone B builder is
`packaging/debian/build_debs.py`. Packages built on a contributor machine are
**not validated** until installed and tested on Debian 13 arm64 hardware, and
even then should be labeled experimental until a clean-Pi test is accepted.

## Pull requests

1. Open an issue or Discussion first for anything large.
2. Keep package names, import paths and the public interfaces stable unless a
   migration is agreed.
3. Add or update tests; run the full suite.
4. Update MODULES.md / HARDWARE.md / CHANGELOG.md when behaviour or support
   changes.
5. Use the pull request template. Do not claim Windows support, physical-Pi
   validation, or a final license in a PR unless those have actually been
   done.
