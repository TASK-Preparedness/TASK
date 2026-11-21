# T.A.S.K.

**Free, open-source, offline-first emergency preparedness software for the Raspberry Pi.**

T.A.S.K. turns a Raspberry Pi into a field station for emergencies and
preparedness: off-grid mesh messaging, offline maps and GPS, amateur/GMRS
radio data, a receive-only software-defined radio, and an offline library and
medical reference reader — all usable with no internet connection.

> **Status: pre-release (Public Alpha in preparation).** Nothing here has been
> published as a release yet. The modules below run daily on the developer's
> Raspberry Pi 5, but the public installer and packages have **not** been
> validated on a clean system. Read [Current limitations](#current-limitations)
> before relying on T.A.S.K. in a real emergency.

T.A.S.K. is and will remain **completely free**: no subscriptions, no paid
editions, no feature paywalls. Donations are entirely optional. It is licensed
under the [GNU GPL v3 or later](LICENSE).

## What it does

| Module | What you can do | Maturity |
|---|---|---|
| Launcher | One dashboard for every T.A.S.K. tool, plus Files, System and App Manager | tested |
| Mesh Network | Send and receive Meshtastic messages over a USB node, with desktop and audible alerts | tested |
| Maps & GPS | Offline maps (MBTiles you provide), live GPS position, waypoints, tracks, GPX | experimental |
| Radio / APRS | Receive APRS through Direwolf; transmit only when you explicitly choose to | experimental |
| SDR Studio | Receive-only RTL-SDR radio: FM/AM/SSB, spectrum, waterfall, scanner | experimental |
| Offline Library & Medical Reader | Read ZIM (Kiwix), PDF, EPUB and text files offline | experimental |
| Devices | See connected devices and which app owns them | experimental |
| Weather | Shows the status of local weather decoders/data only (no forecasts) | incomplete |
| Mission Planner, Firmware Manager, two-way Radio | Designed, not built | planned |
| Windows version | Not built or tested yet | unavailable |

What the maturity words mean, and the full per-module detail, is in
[MODULES.md](MODULES.md).

## Supported hardware

* **Raspberry Pi 5** running **Debian 13 "trixie" / Raspberry Pi OS (64-bit)** — the only verified board.
* Raspberry Pi 4/400 — expected to work, **untested**.
* Raspberry Pi 3 and Zero 2 W — **experimental** (low memory; reduced module set).
* 32-bit operating systems and Pi 1/2/Zero (original) — **not supported**.

Radios and accessories (Heltec V3, T-Beam, T-Deck, RTL-SDR Blog V4, u-blox
GPS, BTECH UV-PRO …) are listed with their verification status in
[HARDWARE.md](HARDWARE.md).

## Safety first

* T.A.S.K. **never transmits on any radio unless you explicitly tell it to**, and
  amateur transmit is disabled until you enter your own licensed callsign.
* The installer **never flashes firmware, never takes control of your radios**,
  never enables background services and never starts anything automatically.
* Device discovery is read-only.

## Installing

The installer is in development. See [INSTALL.md](INSTALL.md) for what works
today (building from source, the dry-run installer) and
[QUICKSTART.md](QUICKSTART.md) for first steps. Offline installation is
described in [OFFLINE.md](OFFLINE.md).

## Current limitations

* No published release, `.deb` repository or offline bundle yet.
* The Raspberry Pi installer only performs a **dry run** (it shows exactly what it would do).
* Several modules await physical hardware acceptance tests (see [TESTING.md](TESTING.md)).
* No map, ZIM, medical or firmware content is included — you supply your own.
* Windows support is in early development and has never been run on Windows ([WINDOWS.md](WINDOWS.md)).

## Get involved

Radio operators, emergency volunteers, developers, testers and writers are all
welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md), report problems with
the issue templates, and talk with us in GitHub Discussions
([docs/DISCUSSIONS.md](docs/DISCUSSIONS.md)). Please follow our
[Code of Conduct](CODE_OF_CONDUCT.md). Security issues: [SECURITY.md](SECURITY.md).

## Repository map

See [docs/REPOSITORY-LAYOUT.md](docs/REPOSITORY-LAYOUT.md). Third-party
components and their licenses: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Plans: [ROADMAP.md](ROADMAP.md). History: [CHANGELOG.md](CHANGELOG.md).

Copyright © 2026 Joshua Sturtz and T.A.S.K. contributors.
