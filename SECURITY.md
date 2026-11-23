# Security policy

T.A.S.K. is used in emergencies and can be used with radios, so security and
RF-safety reports are taken seriously.

> **EXPERIMENTAL ALPHA — NOT VALIDATED ON A PHYSICAL RASPBERRY PI.**

## Reporting a vulnerability

Please **do not** open a public issue.

Use GitHub's private vulnerability reporting when it is enabled on
https://github.com/TASK-Preparedness/TASK (*Security → Report a vulnerability*).

A dedicated security e-mail address will be listed here once the owner
approves one. Until then, if private GitHub reporting is not yet enabled,
do not post the details publicly; wait for the publishing checklist to
enable the private channel, or ask the copyright holder directly if you
already have a private way to reach them.

Include the affected module and version, hardware, steps to reproduce, and
the impact. Redact secrets, callsigns, and locations you do not need to
include.

## What counts

* Anything that could transmit on a radio without explicit operator action.
* Bypassing task-core device ownership, accounts or session checks.
* Code execution, privilege escalation, path traversal (for example in the
  ZIM/EPUB reader).
* Leaking callsigns, locations, messages or credentials.
* Installer behaviour that changes system configuration unexpectedly.

## Supported versions

This experimental alpha: only the current published pre-release and the
`main` branch of https://github.com/TASK-Preparedness/TASK will receive
fixes, once they are published. Older unpublished snapshots are not a
supported security baseline.
