# R.A.I.N. architecture baseline

Status: accepted.
Appliance base: Raspberry Pi OS Lite, 64-bit (Debian 13 Trixie underneath). Confirmed.
Phase 1 userspace must also run on the existing Debian 13 ARM64 prototype.
Phase 1 specification: [PHASE-1.md](PHASE-1.md), frozen. Coding waits for an explicit authorization.
Phase 2 specification: [PHASE-2.md](PHASE-2.md) r3, approved 2026-10-08. Its section 1.1 amendment is applied below
(components table, diagram note, and the first locked principle).

R.A.I.N. (Remote Access Information Network) is a self-contained field computer for a Raspberry Pi 5. It must keep working when the Internet, the cellular network, and the electrical grid are unavailable. The first flashable image is not this phase. An image is built only after the system has been tested on Raspberry Pi hardware.

## Components

Primary R.A.I.N. components (amended by PHASE-2.md section 1.1):

| Component | Privilege | Job |
|---|---|---|
| R.A.I.N. Console (`rain-console`) | unprivileged, the desktop user | Native PySide6/Qt Widgets interface: the primary **local** interface on the Pi's own display. The shell and dashboard that later hosts module panels. Phase 2. |
| rain-portal (R.A.I.N. web portal) | unprivileged | **Remote/client** interface for phones, tablets, and laptops on the R.A.I.N. Wi-Fi/LAN. The concept is kept, not retired; it is built in Phase 3 or later. |
| rain-core | unprivileged | Orchestration and the local API. Owns devices, modules, capabilities, and authorization. |

rain-core is not a root daemon. Reading udev is not a reason for it to run as root. The long-running process uses a dedicated service account, `rain-core`, and only the filesystem rights that account needs.

Privileged work stays out of this process. When a later phase must start or stop a unit, change NetworkManager, power off, mount removable media, or apply an update, that action goes through a narrow boundary: a dedicated helper or a polkit action. It is not solved by granting rain-core sudo or by running the core as root. Phase 1 does not build that helper.

External services stay independent and systemd-supervised. rain-core does not absorb them. A failed optional service must not take the portal down.

Supervised outside the core, when that program is installed and wanted:

- nginx
- NetworkManager
- gpsd
- kiwix-serve
- Direwolf
- Meshtastic (serial client or meshtasticd)
- future satellite workers

Additional R.A.I.N. worker processes are allowed when a job should not live inside rain-core. Workers talk to rain-core. They do not invent a second user interface.

The diagram below is the original Phase 1 picture. Under the section 1.1 amendment the local display runs the
native R.A.I.N. Console (a direct rain-core client over the same unix socket); rain-portal serves remote clients only.

```text
kiosk browser                         phones on the access point
        │                                      │
        └──────────── rain-portal ─────────────┘
                            │  unix socket, local only
                       rain-core          (account rain-core, not root)
                       devices, modules, capabilities, auth
                            │
            systemd units, present only if installed
            gpsd · kiwix-serve · direwolf · meshtastic · nginx
            NetworkManager · future workers
```

## Process identity and human identity

These are different and stay different.

Phase 1 authenticates the calling process with `SO_PEERCRED` and `/etc/rain/auth.toml`. That file exists so local tests can map a Unix uid to a role. It is not the browser login system.

A Unix uid cannot be the final authorization for people using the portal. Every browser user will share the `rain-portal` process, and rain-core will see that one peer uid for all of them.

The eventual flow, with no token format chosen yet:

```text
Browser user
  → authenticated portal session
  → rain-portal
  → trusted local request to rain-core
    carrying the session authorization context the portal already validated
  → rain-core independently allows or refuses that operation
```

The `rain-portal` account must never be an administrator just because it can open the socket. Phase 1 does not design or implement the session credential.

## Locked principles

- One authority, several clients. rain-core is the only authority for devices, capabilities, roles, and sessions. The native console (local) and the web portal (remote) are both clients of rain-core. Neither holds hardware logic or makes authorization decisions. (Amended by PHASE-2.md section 1.1; it replaces "One web interface for the kiosk and for other devices.")
- Offline-first. Internet is only for optional updates and downloads.
- Modular. A module is data and, later, a worker. It is not a rewrite of the core.
- systemd supervises processes.
- Any optional hardware may be absent. Boot still succeeds.
- Mature programs keep their specialty. R.A.I.N. integrates and supervises.
- Local accounts only. No cloud identity.
- Roles are public, operator, and administrator.
- Medical patient access is not a role. It is a further explicit unlock.
- No cloud dependency for core function.
- No flashable image until the system has been tested on a Raspberry Pi.
- The long-running core stays unprivileged wherever practical.

## Device manager

rain-core contains a Device Manager, the hardware abstraction layer. Modules and workers must not open unstable names such as `/dev/ttyUSB0`.

Identity is taken, in order, from the first stable source that exists:

1. `/dev/serial/by-id`
2. USB vendor id, product id, and serial number
3. manufacturer and product strings
4. other udev properties
5. SDR USB identity
6. a network interface's permanent hardware address, never the kernel name alone
7. a manually assigned persistent alias

The core exposes logical devices:

- `gps.primary`
- `mesh.primary`
- `sdr.primary`
- `radio.primary`

Assignments persist across reboot. A missing device stays assigned and is reported disconnected. It is not a boot failure. Assignment writes survive power loss: temp file in the same directory, flush, fsync the file, rename, fsync the directory. A corrupt assignment file is kept as evidence and is not deleted on sight.

The System screen will eventually show each detected device: identity, logical assignment, connection, and unknown or unassigned. That screen is not part of Phase 1.

Generic USB serial adapters are not automatically claimed. The same CP2102 or CH340 may be a GPS, a Meshtastic radio, or something else. Unambiguous hardware (a known GPS USB id, an RTL-SDR) may be classified. Classification is not the same as "this capability works." There is no automatic logical assignment.

## Capabilities

Modules depend on capabilities, not on a hardware model. A capability is either device-backed or provider-only.

Device-backed: `gps.position`, `radio.rx`, `radio.tx`, `mesh.messaging`, `mesh.position`. Status is `no-device` (logical hardware absent or unassigned), then `no-provider` (hardware present, no worker), then `available` (both ready).

Provider-only: `weather.products`. Status is `no-provider` or `available`. It never reports `no-device`.

An SDR may back `radio.rx`. It does not implicitly back `radio.tx`. Another GPS, SDR, radio, or mesh device can replace the current one without a redesign, as long as it provides the same capability. Plugging in hardware does not, by itself, mark a capability available. Phase 1 registers no providers, so nothing is `available`.

## Medical data

`station.db` and `patients.db` are different files.

- `station.db` holds operational records (waypoints, tasks, radio and mesh logs, power).
- `patients.db` is SQLCipher. It holds patient and incident records only.

Opening an operator or administrator session does not decrypt `patients.db`. An authorized operator or administrator must unlock Medical Patient Access explicitly. Public users have no patient API and no path to that file. Reference medical text is ordinary knowledge and is not stored in `patients.db`.

Phase 1 does not create either database and does not implement any `medical.patients.*` method. A medical module reported ready means only that its manifest loaded.

## Roles

| Role | May do |
|---|---|
| Public | knowledge, public maps, selected manuals and media |
| Operator | communications and field tools |
| Administrator | configuration, services, backup, device assignment |

Public is the default for a device that joins the access point. Patient unlock is an additional secret inside an operator or administrator session, not a fourth role on the Wi-Fi.

## What we write, integrate, and supervise

Write: rain-core, rain-portal, module manifests, device rules, role checks, the first-run wizard, backup and restore, and the image stage.

Integrate: Kiwix, gpsd, local map tiles, the Meshtastic library, Direwolf, and FreeSewing's offline libraries when that module is built. Do not embed the public FreeSewing website.

Leave as separate programs until a later phase: SDR++, GQRX, GNU Radio, Xastir, and a full satellite decoder. Screens show status and the files those programs produced.

## Base operating system

Confirmed appliance base: **Raspberry Pi OS Lite, 64-bit, Debian 13 (Trixie).**

This is Debian 13 for the packages that matter, plus the Pi 5 kernel, firmware, and bootloader. It is not Raspberry Pi OS with a desktop. Phase 1 does not build an image and must pass its automated tests on the current Debian 13 ARM64 prototype. It must not require `vcgencmd` or Raspberry Pi firmware.

pi-gen, on the `arm64` branch with `RELEASE=trixie`, is the image tool because it builds this base. Desktop stages will be skipped. `rpi-image-gen` remains a later option for signed boot or a software bill of materials, not the first image.

Userspace packages used by the appliance (gpsd, Direwolf, nginx, NetworkManager, Chromium, cage) are Debian packages on this base. The RTL-SDR Blog V4 driver and Meshtastic are not solved by the distro choice. They stay later workers and device rules.

## Image, later

`pi-gen` produces `RAIN-OS-x.y.z.img.xz` after hardware tests. Stages 0–2 stay upstream. A single `stage-rain` installs R.A.I.N. Cloud-init in the image is off, so Raspberry Pi Imager's user and Wi-Fi wizard cannot fight the access point. There is no default password. The portal wizard is the only first-run path. Knowledge packs and map regions are imported later. They are not baked into the image.

## Networking, later

The Pi can hold an access point at `192.0.2.1` (an example address from TEST-NET-1, RFC 5737) with no upstream network. Guests reach the portal and nothing else. gpsd, Direwolf, and the core socket are not exposed on that network. Captive-portal behavior is best-effort.

## Resilience, later

SQLite WAL for `station.db`. SQLCipher for `patients.db`. Optional units restart on failure. A later image can use a read-only system partition. Assignment and other small state files use the Phase 1 replace sequence: write a complete temp file in the same directory, flush, fsync the file, rename, fsync the directory. Corrupt state is preserved as evidence rather than deleted. A missing optional device does not stop rain-core.

## Development phases

| Phase | Result |
|---|---|
| 0 | This baseline. |
| 1 | rain-core: manifests, device manager, capabilities, local API. Frozen in [PHASE-1.md](PHASE-1.md). |
| 2 | Portal home screen talking only to the core. Human sessions, distinct from the portal uid. |
| 3 | Kiosk and access point, on hardware, still without an image release. |
| 4 | Kiwix from local ZIMs. |
| 5 | gpsd, local maps, waypoints. |
| 6 | System page from core status. |
| 7 | Meshtastic worker. |
| 8 | SDR and Direwolf status. APRS stations. |
| 9 | Medical reference, then encrypted patients with a separate unlock. |
| 10 | T.A.S.K., files, offline clothing patterns. |
| 11 | First-run wizard, backup, flashable image, only after Pi hardware tests. |
