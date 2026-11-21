<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Radio r3.1 dependency assessment
The authoritative dependency/version table and unresolved packaging metadata are in PACKAGING-AND-ROLLBACK.md. Reviewed imports and signatures are in API-MATRIX.md.

No simulator dependency on BlueZ, bleak, dbus-fast, serial, esptool or Direwolf. Existing task-aprs owns neither audio nor the Direwolf daemon; its KISS/AGW clients are loopback-only. Use shared codec/controllers, not duplicate Radio code. Installed T.A.S.K. exact baseline pins are a first-release safety choice, not a claim every future version is incompatible. Missing Python/PySide6 versions and Mesh Depends/maintainer scripts must be collected before final package control. No new dependency installed or assumed present from this box's environment.
