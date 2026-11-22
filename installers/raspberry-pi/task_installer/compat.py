# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Raspberry Pi compatibility matrix and host gating.

Hard requirements always come from DETECTED facts (userland architecture and
OS release). A manually selected model can only make recommendations
stricter; it can never turn an unsupported architecture or OS into a
supported one. This matches release/common/task-guard.sh (tg_require_host:
arm64 + Debian 13 "trixie").
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .detect import HostFacts

VERIFIED = "verified"
UNTESTED = "untested"
EXPERIMENTAL = "experimental"
UNSUPPORTED = "unsupported"

REQUIRED_ARCH = "arm64"
REQUIRED_OS_ID = {"debian", "raspbian"}   # Raspberry Pi OS (64-bit) reports ID=debian
REQUIRED_CODENAME = "trixie"
REQUIRED_VERSION_ID = "13"


@dataclass(frozen=True)
class ModelInfo:
    family: str
    label: str
    status: str
    min_ram_mib: int
    profile: str           # "full", "no-webengine", "minimal-only", "none"
    note: str


MODELS: dict[str, ModelInfo] = {m.family: m for m in [
    ModelInfo("pi5", "Raspberry Pi 5", VERIFIED, 2048, "full",
              "Verified only as the 8 GB development unit running the installed T.A.S.K. packages on Debian 13 arm64. "
              "This installer itself has NOT been run on it yet."),
    ModelInfo("pi500", "Raspberry Pi 500", UNTESTED, 2048, "full", "Same SoC as Pi 5; not tested."),
    ModelInfo("cm5", "Compute Module 5", UNTESTED, 2048, "full", "Not tested."),
    ModelInfo("pi4", "Raspberry Pi 4", UNTESTED, 2048, "full",
              "Expected to work on 4 GB/8 GB; SDR Studio DSP and the Medical Reader web view are heavier on 2 GB. Not tested."),
    ModelInfo("pi400", "Raspberry Pi 400", UNTESTED, 2048, "full", "Same SoC as Pi 4; not tested."),
    ModelInfo("cm4", "Compute Module 4", UNTESTED, 2048, "full", "Not tested."),
    ModelInfo("pi3", "Raspberry Pi 3", EXPERIMENTAL, 1024, "no-webengine",
              "1 GB RAM: QtWebEngine (Medical/Library web reader) and SDR Studio are not recommended. Not tested."),
    ModelInfo("cm3", "Compute Module 3", EXPERIMENTAL, 1024, "no-webengine", "Not tested."),
    ModelInfo("zero2w", "Raspberry Pi Zero 2 W", EXPERIMENTAL, 512, "minimal-only",
              "512 MB RAM: only the Minimal installation is offered. Not tested."),
    ModelInfo("zero", "Raspberry Pi Zero / Zero W", UNSUPPORTED, 0, "none", "ARMv6, no 64-bit userland."),
    ModelInfo("pi2", "Raspberry Pi 2", UNSUPPORTED, 0, "none", "No arm64 Raspberry Pi OS / Debian 13 target for T.A.S.K."),
    ModelInfo("pi1", "Raspberry Pi 1", UNSUPPORTED, 0, "none", "ARMv6, no 64-bit userland."),
]}


@dataclass
class Verdict:
    ok: bool
    model: ModelInfo | None
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    profile: str = "none"
    manual_mismatch: bool = False


def evaluate(facts: HostFacts, manual_family: str | None = None, min_disk_mib: int = 300) -> Verdict:
    blockers: list[str] = []
    warnings: list[str] = []
    # 1. hard host requirements: detected only, never overridable
    if facts.dpkg_arch != REQUIRED_ARCH:
        blockers.append(f"Userland architecture is {facts.dpkg_arch or 'unknown'} (kernel {facts.kernel_machine}); "
                        f"T.A.S.K. packages are built for {REQUIRED_ARCH} only. Use Raspberry Pi OS (64-bit) / Debian 13 arm64.")
    if (facts.os_id or "").lower() not in REQUIRED_OS_ID or not (
            facts.os_codename == REQUIRED_CODENAME or facts.os_version_id == REQUIRED_VERSION_ID):
        blockers.append(f"Operating system is {facts.os_pretty or 'unknown'}; Debian 13 \"trixie\" (or Raspberry Pi OS based on it) is required.")
    # 2. model: detected wins for hardware facts; manual choice may only be stricter
    detected = MODELS.get(facts.pi_family or "")
    chosen = detected
    mismatch = False
    if manual_family:
        manual = MODELS.get(manual_family)
        if manual is None:
            blockers.append(f"Unknown model selection: {manual_family}")
        elif detected and manual.family != detected.family:
            mismatch = True
            warnings.append(f"You selected {manual.label} but this board reports \"{facts.model}\". "
                            "Detected hardware is used for all checks; your selection can only make choices stricter.")
            chosen = _stricter(detected, manual)
        elif detected is None:
            warnings.append(f"Board model could not be detected; using your selection ({manual.label}) for recommendations only.")
            chosen = manual
    if chosen is None:
        if facts.model is None:
            warnings.append("This does not look like a Raspberry Pi (no device-tree model). Nothing here is tested on other arm64 boards.")
        else:
            warnings.append(f"Unrecognised board: {facts.model}")
    elif chosen.status == UNSUPPORTED:
        blockers.append(f"{chosen.label} is not supported: {chosen.note}")
    elif chosen.status != VERIFIED:
        warnings.append(f"{chosen.label}: {chosen.status}. {chosen.note}")
    # 2b. second, independent read-only source: the board revision code in /proc/cpuinfo
    if facts.revision_family and detected and facts.revision_family != detected.family:
        warnings.append(f"Device-tree model ({facts.model}) and revision code {facts.revision} "
                        f"({facts.revision_family}) disagree; the stricter of the two is used.")
        other = MODELS.get(facts.revision_family)
        if other and chosen:
            chosen = _stricter(chosen, other)
    # 3. resources
    min_ram = chosen.min_ram_mib if chosen else 2048
    if facts.mem_total_mib is not None and facts.mem_total_mib < min_ram * 0.85:
        warnings.append(f"Only {facts.mem_total_mib} MiB RAM detected; {min_ram} MiB recommended.")
    if facts.disk_free_mib is not None and facts.disk_free_mib < min_disk_mib:
        blockers.append(f"Only {facts.disk_free_mib} MiB free disk space; at least {min_disk_mib} MiB needed.")
    if not facts.graphical:
        warnings.append("No graphical session detected: the text installer will be used; T.A.S.K. apps need a desktop to run.")
    profile = chosen.profile if chosen else "full"
    mem = facts.mem_total_mib or facts.revision_mem_mib
    if chosen and chosen.family in ("pi4", "pi400", "cm4") and mem is not None and mem < 1800 and profile == "full":
        profile = "no-webengine"
        warnings.append(f"{chosen.label} with {mem} MiB RAM: the QtWebEngine reader (recommended package) is skipped.")
    return Verdict(ok=not blockers, model=chosen, blockers=blockers, warnings=warnings,
                   profile=profile, manual_mismatch=mismatch)


_ORDER = {"full": 0, "no-webengine": 1, "minimal-only": 2, "none": 3}


def _stricter(a: ModelInfo, b: ModelInfo) -> ModelInfo:
    return a if _ORDER[a.profile] >= _ORDER[b.profile] else b
