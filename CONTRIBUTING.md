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
* Contributions are accepted under the project license, GPL-3.0-or-later,
  with a DCO sign-off. See [Licensing of contributions](#licensing-of-contributions).

## Licensing of contributions

T.A.S.K. uses **inbound = outbound** licensing. You contribute under the same
license the project is distributed under, **GPL-3.0-or-later**. You keep the
copyright in your contribution. There is no copyright assignment.

1. **Sign off every commit** with the
   [Developer Certificate of Origin 1.1](https://developercertificate.org/).
   Use `git commit -s`. This adds a line like
   `Signed-off-by: Your Name <you@example.com>`, which certifies that you wrote
   the change, or otherwise have the right to submit it under the project's
   open source license. Use a name and address you are happy to have recorded
   in public history permanently.
2. **Put the license header on every new source file**, in the file's own
   comment syntax:
   ```
   # SPDX-License-Identifier: GPL-3.0-or-later
   # SPDX-FileCopyrightText: <year> <your name>
   ```
   Don't change or remove other people's copyright or license notices.
   Don't add headers to the 17 frozen files listed in `REUSE.toml`; their
   bytes are pinned by tests.
3. **Third-party code.**
   * Only add code under a GPL-3.0-compatible license.
   * Keep its original copyright and license notice.
   * Add it to [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
   * Say where it came from in the pull request.
   * Don't paste code from sources whose license you don't know, including
     forum posts and AI-chat output that copies existing code.
   * Never copy Meshtastic protocol definitions (`.proto` files or generated
     `*_pb2.py`) into T.A.S.K. code outside `mesh/`.
4. **AI-assisted contributions** are welcome. You are responsible for them as
   for any other change. Say in the pull request that AI tools were used, and
   make sure the result doesn't reproduce third-party code.
5. **Names and logos.** A contribution doesn't grant rights in the T.A.S.K.
   name or logo. See [TRADEMARK.md](TRADEMARK.md).

There is no Contributor License Agreement. DCO sign-off is the only contributor certification in force.

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
