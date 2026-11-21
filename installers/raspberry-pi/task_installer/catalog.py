# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Module catalog: what exists, at which version, and how mature it is.

Versions and maturity come from the verified installed-source inventory of
the development Pi (2026-11-08) and the automated test runs recorded in
TESTING.md. "storage_kib" is the size of the module's own installed files on
the development Pi (Debian dependencies NOT included) and is an ESTIMATE.

Maturity values: stable, tested, experimental, incomplete, planned, unavailable.
Only "tested" and "experimental" modules are installable; planned/unavailable
entries are listed so users can see them but are never presented as working.
"""
from __future__ import annotations

from dataclasses import dataclass, field

INSTALLABLE = {"stable", "tested", "experimental"}


@dataclass(frozen=True)
class Module:
    id: str
    name: str
    packages: tuple[str, ...]
    version: str
    maturity: str
    summary: str
    requires: tuple[str, ...] = ()          # other module ids
    apt_depends: tuple[str, ...] = ()       # notable Debian runtime deps
    hardware: str = "none"
    storage_kib: int = 0
    needs_webengine: bool = False
    essential: bool = False                 # part of Minimal
    offline: str = "fully offline"
    notes: tuple[str, ...] = field(default_factory=tuple)


CATALOG: tuple[Module, ...] = (
    Module("core", "T.A.S.K. Core", ("task-core", "task-core-compat"), "0.3.0", "tested",
           "Device discovery/assignment, accounts and sessions, ownership/exclusion; R.A.I.N. compatibility names and migration.",
           apt_depends=("python3-yaml",), storage_kib=191, essential=True,
           notes=("task-core.service is a system service; the installer never enables or restarts it without consent.",
                  "task_core.__version__ still reports 0.2.1 (package is 0.3.0).")),
    Module("comms", "Shared communications library", ("python3-task-comms",), "0.3.1", "tested",
           "Notifications, ownership coordination, TX policy and feeds shared by Mesh and Radio.", storage_kib=72),
    Module("launcher", "T.A.S.K. Launcher", ("task-launcher",), "0.3.7", "tested",
           "Dashboard and built-in Files, System, App Manager, Medical reference finder and Weather status views.",
           apt_depends=("python3-pyside6.qtwidgets", "python3-pyside6.qtsvg"), storage_kib=448, essential=True,
           notes=("Medical Reader crash fix (0.3.7) awaits its physical Pi acceptance test.",)),
    Module("devices", "Devices (T.A.S.K. Console)", ("task-console",), "0.2.0", "experimental",
           "Device list and assignments through task-core.", requires=("core",), storage_kib=131,
           notes=("Launcher tile still prefers the legacy /usr/local/bin/task-console path.",)),
    Module("mesh", "Mesh Network (Meshtastic/MeshCore)", ("task-mesh",), "0.3.1", "tested",
           "Native Meshtastic field station with background message service and desktop/audible notifications.",
           requires=("comms",), apt_depends=("python3-serial", "python3-protobuf", "python3-pubsub", "pulseaudio-utils"),
           hardware="Meshtastic node over USB serial (verified: Heltec V3 915 MHz)", storage_kib=2053,
           notes=("Audible alert: maintained source plays a user-generated WAV; the WAV is NOT shipped (CC-BY-SA source).",
                  "The background service is a user unit and is never enabled automatically.")),
    Module("maps", "Maps & GPS", ("task-maps",), "0.1.1", "experimental",
           "Offline MBTiles map viewer, gpsd position, waypoints/tracks/GPX.", apt_depends=("gpsd (recommended)",),
           hardware="USB GPS via gpsd (verified: u-blox 7)", storage_kib=241,
           offline="offline with user-supplied MBTiles; map downloads optional and online",
           notes=("No map data is bundled.",)),
    Module("radio", "Radio / APRS", ("task-aprs",), "0.1.0", "experimental",
           "APRS receive through an existing Direwolf; transmit only by explicit operator action; separate GMRS data profile.",
           requires=("comms",), apt_depends=("direwolf (user-configured)",),
           hardware="Direwolf-compatible TNC/radio; BTECH UV-PRO Bluetooth KISS is UNVERIFIED", storage_kib=72,
           notes=("Bidirectional APRS (Phase 5A Milestone B) is not implemented yet.", "RF transmit is off by default.")),
    Module("sdr", "SDR Studio", ("task-sdr",), "0.2.4", "experimental",
           "Receive-only RTL-SDR: WFM/NFM/AM/USB/LSB, spectrum, waterfall, scanner.",
           apt_depends=("python3-numpy", "python3-scipy", "python3-pyside6.qtmultimedia", "SoapySDR RTL-SDR module"),
           hardware="RTL-SDR (e.g. RTL-SDR Blog V4)", storage_kib=214,
           notes=("0.2.4 audio pipeline awaits its physical Pi acceptance test.", "Receive only; never transmits.")),
    Module("library", "Offline Library & Medical Reader", ("task-resources",), "0.2.4", "experimental",
           "Reader for ZIM, PDF, EPUB and text; read-only Kiwix/medical collections.",
           apt_depends=("python3-libzim", "python3-pyside6.qtwebenginewidgets (recommended)"), storage_kib=241,
           needs_webengine=True, offline="offline with user-supplied ZIM/PDF/EPUB content",
           notes=("No ZIM, medical or other third-party content is bundled.",)),
    Module("mission", "Mission Planner", (), "0.0.0", "planned", "Launcher tile only; no source exists."),
    Module("weather-decoders", "Weather data/decoders", (), "0.0.0", "planned",
           "Launcher shows decoder/data status only; no forecast engine or decoder integration exists."),
    Module("firmware", "Firmware Manager", (), "0.0.0", "planned",
           "Design documents only (offline vault, explicit-confirmation flashing). No code; flashing is not available."),
    Module("radio-2way", "Two-way Radio (task-radio, Phase 5A)", (), "0.0.0", "planned",
           "Design documents only; Milestone B coding not yet approved."),
    Module("windows", "Windows build", (), "0.0.0", "unavailable", "Not built or tested on Windows."),
)

BY_ID = {m.id: m for m in CATALOG}


def installable(profile: str = "full") -> list[Module]:
    mods = [m for m in CATALOG if m.maturity in INSTALLABLE]
    if profile == "minimal-only":
        return [m for m in mods if m.essential]
    return mods


def resolve(ids, profile: str = "full") -> list[Module]:
    """Return the selected modules plus everything they require, in install order, essentials first."""
    allowed = {m.id for m in installable(profile)}
    wanted: list[str] = []

    def add(i):
        if i not in BY_ID:
            raise KeyError(f"unknown module {i}")
        if i not in allowed:
            raise ValueError(f"module {i} is not installable here ({BY_ID[i].maturity}, profile {profile})")
        for r in BY_ID[i].requires:
            add(r)
        if i not in wanted:
            wanted.append(i)

    for m in installable(profile):
        if m.essential:
            add(m.id)
    for i in ids:
        add(i)
    return [BY_ID[i] for i in wanted]
