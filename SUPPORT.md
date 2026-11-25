# Support and volunteer reporting

T.A.S.K. is an **experimental alpha**. There is no official support desk and
no project email address. This page is how volunteer testers and users can
report problems.

> **EXPERIMENTAL ALPHA — NOT VALIDATED ON A PHYSICAL RASPBERRY PI.**

## Before you ask

* [docs/VOLUNTEER-TESTING.md](docs/VOLUNTEER-TESTING.md) — volunteer test round 1 (install, start, remove)
* [INSTALL.md](INSTALL.md) — install, checksums, uninstall, rollback
* [SAFETY.md](SAFETY.md) — RF, licensing, backups, spare SD card
* [KNOWN-ISSUES.md](KNOWN-ISSUES.md) — problems we already know about
* [HARDWARE.md](HARDWARE.md) — what has and has not been tested
* [TESTING.md](TESTING.md) — automated test results (not a Pi test)

## Where to report

| Kind of report | Where |
|---|---|
| Bug, crash, wrong behaviour | GitHub issue: **Bug report** template |
| I tried a test or an install (pass, fail, skip, or blocked) | GitHub issue: **Volunteer test report** template |
| My board, radio, GPS or SDR | GitHub issue: **Hardware compatibility report** template |
| Packages, checksums or detection failed | GitHub issue: **Installation problem** template |
| A feature idea | GitHub issue: **Feature request** template, or Discussions |
| A question, not a bug | GitHub Discussions (once enabled; see [docs/DISCUSSIONS.md](docs/DISCUSSIONS.md)) |
| Security, unexpected transmit, or a privilege issue | **Private** report only — [SECURITY.md](SECURITY.md) |

The public repository is https://github.com/TASK-Preparedness/TASK.

General support is through GitHub Issues. Security reports use GitHub
private vulnerability reporting, as described in [SECURITY.md](SECURITY.md).
Please do not open a blank issue; the templates ask for the details that make
a report usable.

## What to include

Run these **one at a time** and paste the output (you may redact anything
personal):

```
cat /proc/device-tree/model; echo; grep Revision /proc/cpuinfo; dpkg --print-architecture; cat /etc/os-release
```

```
dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\n' 'task-*' python3-task-comms
```

Also include: what you were trying to do, what happened, what you expected,
and redacted logs. Remove callsigns, locations, GPS tracks, message text,
device serial numbers, passwords, and home-directory paths.

## What we cannot do yet

* We cannot remotely access your Pi, and you should not offer us SSH to a
  production or working system.
* We cannot promise a fix date.
* Windows is not supported in this alpha ([WINDOWS.md](WINDOWS.md)).
* There is no donation link in this release.
