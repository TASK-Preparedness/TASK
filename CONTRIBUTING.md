# Contributing to T.A.S.K.

Thank you! T.A.S.K. is built by and for radio operators, emergency volunteers,
developers and everyday people. Every contribution is welcome: testing on your
hardware, bug reports, documentation, translations and code.

## Ground rules

* Be kind — see the [Code of Conduct](CODE_OF_CONDUCT.md).
* Never commit secrets, callsign databases, personal data, device serial numbers,
  your own config files or machine-specific paths.
* Never add code that transmits on a radio without an explicit operator action,
  starts services automatically, flashes firmware without explicit confirmation,
  or uses `shell=True`.
* Report results honestly: say what you tested, on what hardware, and what you did not test.
* By contributing you agree your work is licensed GPL-3.0-or-later. Add the SPDX
  header to every new `.py`/`.sh` file:
  ```
  # SPDX-License-Identifier: GPL-3.0-or-later
  # SPDX-FileCopyrightText: <year> <your name>
  ```

## Development setup (Debian 13 trixie)

```bash
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
`release/corrections/build_sdr_024.py`. Packages built on a contributor machine are
**not validated** until installed and tested on Debian 13 arm64 hardware.

## Pull requests

1. Open an issue or Discussion first for anything large.
2. Keep package names, import paths and the public interfaces stable unless a migration is agreed.
3. Add or update tests; run the full suite.
4. Update MODULES.md / HARDWARE.md / CHANGELOG.md when behaviour or support changes.
