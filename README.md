# T.A.S.K.

**Tactical Access Support Kit** — free-of-charge, offline-first emergency
preparedness software for the Raspberry Pi.

> ## ⚠️ READ FIRST — EXPERIMENTAL ALPHA, SAFETY AND RADIO WARNINGS
>
> * **EXPERIMENTAL ALPHA — NOT VALIDATED ON A PHYSICAL RASPBERRY PI.** The
>   public packages, installer and this source tree have not been installed or
>   accepted on a clean physical Raspberry Pi. Treat every package as
>   experimental. Do not rely on T.A.S.K. as your only tool in a real
>   emergency. T.A.S.K. is not a substitute for emergency services.
> * **RECEIVE-ONLY BY DEFAULT.** T.A.S.K. must never transmit on any radio
>   unless a licensed operator explicitly tells it to. Amateur transmit stays
>   disabled until you enter your own licensed callsign. Transmit-capable
>   features are experimental. **Do not transmit if you are not licensed and
>   allowed to.** You are responsible for knowing the law where you are.
> * **NO AUTOMATIC INSTALL, FIRMWARE FLASHING OR SERVICE START.** The installer
>   is a dry run only. It never flashes firmware, never takes control of your
>   radios, and never starts anything automatically.
> * **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.** Any radio, GPS, SDR,
>   board or feature not listed as tested in [HARDWARE.md](HARDWARE.md) carries
>   this label. Test on a spare SD card, never on a working system.
>
> Read [SAFETY.md](SAFETY.md) and [KNOWN-ISSUES.md](KNOWN-ISSUES.md) before you
> install anything.
>
> This is the `v0.1.0-alpha.1` experimental public alpha for volunteer testers and
> review. The modules below run daily on the developer's Raspberry Pi 5, and
> automated tests plus an emulated Debian 13 arm64 chroot have been run on a
> separate x86_64 build machine. **The public packages, installer, and this
> source tree have not been installed or accepted on a clean physical
> Raspberry Pi.**

T.A.S.K. turns a Raspberry Pi into a field station for emergencies and
preparedness: off-grid mesh messaging, offline maps and GPS, amateur/GMRS
radio data, a receive-only software-defined radio, and an offline library and
medical reference reader — all usable with no internet connection.

T.A.S.K. is **free software** under the GNU GPL, version 3 or later, and
stays **free of charge for everyone**: no subscriptions, no paid editions, no
paywalled essential features. See [License](#license) and
[Project commitments and funding](#project-commitments-and-funding).

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/t.a.s.k.prepardness)

An independent Meshtastic bridge is planned as a future milestone. It is
not a blocker for this experimental alpha.

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
* Security reports go through GitHub private vulnerability reporting
  (see [SECURITY.md](SECURITY.md)). General support is via GitHub Issues.
  Optional financial support is described in [Support T.A.S.K.](#support-task).

## Project commitments and funding

These are promises from the project maintainer, Joshua Sturtz, also recorded in [PROJECT-COMMITMENTS.md](PROJECT-COMMITMENTS.md). They are
**not license terms**. Your rights to the software come from the GPL (see
[License](#license)), and nothing here adds to or limits them.

* **Free, permanently, for essential preparedness.** The essential emergency
  preparedness features of T.A.S.K. will stay free of charge, work fully
  offline, and need no subscription, account or internet connection. That
  includes mesh messaging, offline maps and GPS, radio data, receive-only SDR,
  and the offline library and medical reference reader.
* **No paywalled essential features.** There is no paid edition of the
  essential features, and none is planned.
* **Optional donations.** Donations help pay for hardware testing and
  development. They are entirely optional, and they never unlock features.
  See [Support T.A.S.K.](#support-task).
* **Official commercial services.** Joshua Sturtz may offer official T.A.S.K.
  hardware kits, professional installation, training, support and custom
  deployments. These pay for hardware and people's time, not for the software.
  The software on an official kit is the same free GPL software, with its
  complete source code and your full GPL rights. Only Joshua Sturtz, or someone
  he authorizes, may call a kit or service "official" or "certified" (see
  [TRADEMARK.md](TRADEMARK.md)).
* **Anyone may build a business on T.A.S.K.** The GPL lets anyone sell copies,
  kits or services, including renamed versions, as long as they follow the
  GPL and the trademark policy.

## Support T.A.S.K.

Financial contributions are entirely optional. T.A.S.K. stays free software
under the GPL, and it stays free of charge for essential preparedness
features. No software features are, or will be, restricted based on
financial contributions.

Contributions support development time, equipment, testing, maintenance
and future improvements.

[![Buy Me a Coffee](https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png)](https://buymeacoffee.com/t.a.s.k.prepardness)

The voluntary funding page is <https://buymeacoffee.com/t.a.s.k.prepardness>.
GitHub also lists this link from `.github/FUNDING.yml`.

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

## License

This section is a description of the project's license choice. It is not
legal advice.

T.A.S.K. is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version (`GPL-3.0-or-later`). It is distributed WITHOUT ANY WARRANTY. See
[LICENSE](LICENSE) for the full text.

* The `task-mesh` package bundles meshtastic, which is GPL-3.0-only, so that
  package as a whole is distributed under GPL-3.0.
* Third-party components keep their own licenses and notices; see
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
* The T.A.S.K. name and logo are covered by [TRADEMARK.md](TRADEMARK.md).
  That policy does not limit your rights under the GPL.

Copyright (C) 2026 Joshua Sturtz and T.A.S.K. contributors.

## Repository map

See [docs/REPOSITORY-LAYOUT.md](docs/REPOSITORY-LAYOUT.md). Third-party
components and their licenses: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Plans: [ROADMAP.md](ROADMAP.md). History: [CHANGELOG.md](CHANGELOG.md).
