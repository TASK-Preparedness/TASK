# Security policy

T.A.S.K. is used in emergencies and can be used with radios, so security and
RF-safety reports are taken seriously.

> **EXPERIMENTAL ALPHA — NOT VALIDATED ON A PHYSICAL RASPBERRY PI.**

## Reporting a vulnerability

Please **do not** open a public issue.

Report security and RF-safety problems through GitHub's private
vulnerability reporting on https://github.com/TASK-Preparedness/TASK:

**Security → Report a vulnerability**

(That form is enabled as the first step when the project is published.)

There is no security email address. Do not send reports to a personal
mailbox, and do not post exploit details in a public issue, discussion,
or pull request.

Include the affected module and version, hardware, steps to reproduce,
and the impact. Redact secrets, callsigns, and locations you do not need
to include.

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
fixes, once they are published.
