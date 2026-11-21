# Security policy

T.A.S.K. is used in emergencies and controls radios, so security and RF safety
reports are taken seriously.

## Reporting a vulnerability

Please **do not** open a public issue. Use GitHub's private vulnerability
reporting: *Security → Report a vulnerability* on
https://github.com/TASK-Preparedness/TASK (to be enabled when the repository is
published). A dedicated security e-mail address will be listed here once the
maintainer approves one.

Include affected module and version, hardware, steps to reproduce and impact.

## What counts

* Anything that could transmit on a radio without explicit operator action.
* Bypassing task-core device ownership, accounts or session checks.
* Code execution, privilege escalation, path traversal (e.g. in the ZIM/EPUB reader).
* Leaking callsigns, locations, messages or credentials.
* Installer behaviour that changes system configuration unexpectedly.

## Supported versions

Pre-release: only the current `main` branch receives fixes.
