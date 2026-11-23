# T.A.S.K.

**Tactical Access Support Kit** — free-of-charge, offline-first emergency
preparedness software for the Raspberry Pi.

> **EXPERIMENTAL ALPHA — NOT VALIDATED ON A PHYSICAL RASPBERRY PI.**
>
> This is a proposed `v0.1.0-alpha.1` public snapshot for volunteer testers and
> review. The modules below run daily on the developer's Raspberry Pi 5, and
> automated tests plus an emulated Debian 13 arm64 chroot have been run on a
> separate x86_64 build machine. **The public packages, installer, and this
> source tree have not been installed or accepted on a clean physical
> Raspberry Pi.** Treat every package as experimental. Do not rely on T.A.S.K.
> as your only tool in a real emergency. Read [SAFETY.md](SAFETY.md) and
> [KNOWN-ISSUES.md](KNOWN-ISSUES.md) before you install anything.

T.A.S.K. turns a Raspberry Pi into a field station for emergencies and
preparedness: off-grid mesh messaging, offline maps and GPS, amateur/GMRS
radio data, a receive-only software-defined radio, and an offline library and
medical reference reader — all usable with no internet connection.

T.A.S.K. is intended to remain **free of charge for everyone**: no
subscriptions, no paid editions, no feature paywalls. Donations, if offered,
will be optional. A project-wide license has **not** been approved yet; see
[LICENSE](LICENSE) (`LICENSE PENDING OWNER APPROVAL`). Do not treat historical
GPL headers or per-module `LICENSE` files as the final project license.

**Windows is not supported** in this alpha. There is no Windows build, and
nothing has been tested on Windows. See [WINDOWS.md](WINDOWS.md).

## Module status

| Module | What you can do | Status |
|---|---|---|
| Launcher | One dashboard for every T.A.S.K. tool, plus Files, System and App Manager | tested on the development Pi; public package experimental |
| Mesh Network | Send and receive Meshtastic messages over a USB node, with desktop and audible alerts | tested on the development Pi; public package experimental |
| T.A.S.K. Core | Device enumeration, ownership, accounts and sessions | tested on the development Pi; public package experimental |
| Maps & GPS | Offline maps (MBTiles you provide), live GPS position, waypoints, tracks, GPX | experimental |
| Radio / APRS | Receive APRS through Direwolf; transmit only when you explicitly choose to | experimental |
| SDR Studio | Receive-only RTL-SDR radio: FM/AM/SSB, spectrum, waterfall, scanner | experimental |
| Offline Library & Medical Reader | Read ZIM (Kiwix), PDF, EPUB and text files offline | experimental |
| Devices | See connected devices and which app owns them | experimental |
| Weather | Shows the status of local weather decoders/data only (no forecasts) | incomplete |
| Mission Planner, Firmware Manager, two-way Radio | Designed, not built | planned |
| Windows version | Not built or tested | unavailable |

What those status words mean, and the full per-module detail, is in
[MODULES.md](MODULES.md).

For this volunteer alpha, the intended Debian packages are: `task-core` 0.3.0,
`task-core-compat` 0.3.0, `python3-task-comms` 0.3.1, `task-launcher` 0.3.8,
`task-mesh` 0.3.2~alpha1, `task-maps` 0.1.1, `task-aprs` 0.1.0, `task-sdr` 0.2.4,
`task-resources` 0.2.4 and `task-console` 0.2.1~alpha1. All of them are
**experimental and not validated on a physical Raspberry Pi.**

## Supported hardware (this alpha)

Volunteer testing for this experimental alpha is requested **only** on:

* a **Raspberry Pi 5** running **Debian 13 "trixie" arm64** (or Raspberry Pi OS
  64-bit based on trixie), preferably on a **spare SD card**, not a production
  system.

Other boards (Pi 4, Pi 400, Pi 3, Zero 2 W, memory variants) are described in
[HARDWARE.md](HARDWARE.md) but are **not** part of this test call. 32-bit
operating systems and Debian 12 or older are not supported. Windows is not
supported.

Radios and accessories (Heltec V3, T-Beam, T-Deck, RTL-SDR, u-blox GPS,
BTECH UV-PRO, and others) are listed with their verification status in
[HARDWARE.md](HARDWARE.md).

## Safety first

* T.A.S.K. is **receive-only by default**. It must never transmit on any radio
  unless you explicitly tell it to. Amateur transmit stays disabled until you
  enter your own licensed callsign.
* You are responsible for knowing the law where you are (including amateur and
  GMRS licensing). Do not transmit if you are not licensed and allowed to.
* T.A.S.K. is **not a substitute for emergency services**. Call 911 (or your
  local emergency number) in a life-threatening situation.
* The installer **does not install packages yet** (dry run only). It never
  flashes firmware, never takes control of your radios, never enables
  background services, and never starts anything automatically.
* Device discovery is read-only.

Please read [SAFETY.md](SAFETY.md) before installing or attaching a radio.

## Installing

Volunteer test round 1 (spare-card Pi 5, install / start / remove, no radios):
start with [docs/VOLUNTEER-TESTING.md](docs/VOLUNTEER-TESTING.md). The longer
reference, including SHA-256 checks, uninstall and rollback, is
[INSTALL.md](INSTALL.md). First steps after a successful install:
[QUICKSTART.md](QUICKSTART.md). Offline installation (planned, not in this
alpha): [OFFLINE.md](OFFLINE.md).

The graphical/text installer currently **only performs a dry run**. Volunteer
installs use verified `.deb` packages and `apt`, on a spare card.

## Current limitations

* Experimental alpha: no physical-Pi validation of the public packages or
  installer.
* The Raspberry Pi installer only performs a **dry run**.
* Several modules still await physical hardware acceptance tests (see
  [TESTING.md](TESTING.md) and [KNOWN-ISSUES.md](KNOWN-ISSUES.md)).
* No map, ZIM, medical or firmware content is included — you supply your own,
  under each work's own license.
* The mesh alert sound is not shipped (it is derived from a CC-BY-SA-3.0
  source). Generate it yourself with `scripts/generate-mesh-alert.sh` if you
  want audible alerts. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
* **No Windows support** is claimed or provided.
* Maintainer contact, donation link, and the project-wide license are still
  pending owner approval.

## Volunteer testing and problem reports

If you test this alpha, thank you. Please read [CONTRIBUTING.md](CONTRIBUTING.md)
and [SUPPORT.md](SUPPORT.md), then use the GitHub issue templates:

* **Bug report** — something does not work
* **Volunteer test report** — pass, fail, skip, or blocked
* **Hardware compatibility report** — what worked on your board or radio
* **Installation problem** — packages or detection failed

Please redact callsigns, locations, device serial numbers, messages, and
passwords before posting. Follow the [Code of Conduct](CODE_OF_CONDUCT.md).
Security issues: [SECURITY.md](SECURITY.md) (do not open a public issue).

## Repository map

See [docs/REPOSITORY-LAYOUT.md](docs/REPOSITORY-LAYOUT.md). Third-party
components and their licenses: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Plans: [ROADMAP.md](ROADMAP.md). History: [CHANGELOG.md](CHANGELOG.md).

Copyright © 2026 Joshua Sturtz and T.A.S.K. contributors.
