# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Installation, repair, update and uninstall plans.

A plan is an ordered list of Steps. Each Step is an argv list (never a shell
string) plus flags saying whether it needs root and whether it needs the
network. This version only PRINTS plans (dry run); see executor.py.

Safety rules encoded here (and tested):
* never `apt-get purge`, never `apt-get autoremove`, never `--purge`;
* never enable/start/restart a systemd unit, never add autostart entries;
* never flash firmware, open a radio, or transmit;
* user data (~/.config/task-*, ~/.local/share/task-*) and /etc/task are kept;
* fully-offline installs use only local .deb files / a local repository and
  pass `--no-download` so apt fails instead of silently downloading.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .catalog import BY_ID, Module, installable, resolve
from .compat import Verdict

COMPLETE, CUSTOM, MINIMAL = "complete", "custom", "minimal"
SOURCE_OFFLINE, SOURCE_ONLINE = "offline", "online"


@dataclass
class Step:
    description: str
    argv: list[str]
    root: bool = False
    network: bool = False


@dataclass
class Plan:
    action: str
    modules: list[Module] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    storage_kib: int = 0
    network_required: bool = False

    def render(self) -> str:
        lines = [f"Action: {self.action}"]
        if self.modules:
            lines.append("Modules:")
            for m in self.modules:
                lines.append(f"  - {m.name} {m.version} [{m.maturity}] ({', '.join(m.packages)})")
            lines.append(f"Estimated size of T.A.S.K. files: {self.storage_kib} KiB (Debian dependencies not included)")
        lines.append("Network: " + ("REQUIRED for some steps" if self.network_required else "not required"))
        lines.append("Commands (dry run, not executed):")
        for s in self.steps:
            prefix = "sudo " if s.root else ""
            lines.append(f"  # {s.description}")
            lines.append("  " + prefix + " ".join(_q(a) for a in s.argv))
        for n in self.notes:
            lines.append(f"Note: {n}")
        return "\n".join(lines)


def _q(a: str) -> str:
    return a if a and all(c.isalnum() or c in "-_./=:+~,@" for c in a) else "'" + a.replace("'", "'\\''") + "'"


def _packages(mods) -> list[str]:
    out: list[str] = []
    for m in mods:
        for p in m.packages:
            if p not in out:
                out.append(p)
    return out


def select(mode: str, verdict: Verdict, custom_ids=()) -> list[Module]:
    if not verdict.ok:
        raise PermissionError("host is not compatible: " + "; ".join(verdict.blockers))
    profile = verdict.profile
    if profile == "minimal-only" and mode != MINIMAL:
        raise ValueError("this board only supports the Minimal installation")
    if mode == MINIMAL:
        return resolve([], profile)
    if mode == COMPLETE:
        return resolve([m.id for m in installable(profile)], profile)
    if mode == CUSTOM:
        return resolve(list(custom_ids), profile)
    raise ValueError(f"unknown mode {mode}")


def install_plan(mods, verdict: Verdict, source: str = SOURCE_OFFLINE, deb_dir: str | None = None) -> Plan:
    pkgs = _packages(mods)
    plan = Plan("install", list(mods), storage_kib=sum(m.storage_kib for m in mods))
    no_rec = verdict.profile == "no-webengine"
    if source == SOURCE_OFFLINE:
        d = Path(deb_dir or "./debs")
        plan.steps.append(Step("verify the offline bundle checksums", ["sha256sum", "-c", "SHA256SUMS"]))
        argv = ["apt-get", "install", "--no-download"] + (["--no-install-recommends"] if no_rec else []) + \
               [str(d / f"{p}_*.deb") for p in pkgs]
        plan.steps.append(Step("install T.A.S.K. packages from local files only (fails instead of downloading)", argv, root=True))
        plan.notes.append("Package file names are resolved from the bundle manifest at run time; the glob shown is illustrative.")
    else:
        plan.network_required = True
        plan.steps.append(Step("refresh package lists (online)", ["apt-get", "update"], root=True, network=True))
        plan.steps.append(Step("install T.A.S.K. packages and Debian dependencies (online)",
                               ["apt-get", "install"] + (["--no-install-recommends"] if no_rec else []) + pkgs,
                               root=True, network=True))
        plan.notes.append("Online installation needs a published T.A.S.K. apt source; none exists yet (Public Alpha decision pending).")
    if no_rec:
        plan.notes.append("Low-memory board: recommended packages (QtWebEngine reader) are skipped.")
    if any(m.id == "mesh" for m in mods):
        plan.notes.append("Mesh background service is NOT enabled. Enable it later yourself from Mesh > Network Status if wanted.")
        plan.notes.append("Optional audible alert: run scripts/generate-mesh-alert.sh as your user (needs ffmpeg and sound-theme-freedesktop).")
    if any(m.id == "radio" for m in mods):
        plan.notes.append("Radio/APRS transmit stays disabled until you enter your own licensed callsign and enable it.")
    plan.notes.append("No service is enabled or restarted, no device is opened, nothing is flashed or transmitted.")
    return plan


def repair_plan(installed: dict[str, str]) -> Plan:
    pkgs = sorted(installed)
    plan = Plan("repair")
    plan.steps.append(Step("check installed files against package checksums (read-only)", ["dpkg", "--verify"] + pkgs))
    plan.steps.append(Step("re-install the same versions from the offline bundle", ["apt-get", "install", "--reinstall", "--no-download"] +
                           [f"./debs/{p}_{v}_*.deb" for p, v in sorted(installed.items())], root=True))
    plan.notes.append("dpkg --verify will list intentional local edits (e.g. a hand-modified notifier); review before re-installing, "
                      "because re-installing overwrites changed package files. Back them up first.")
    return plan


def update_plan(installed: dict[str, str], mods) -> Plan:
    plan = Plan("update", list(mods), storage_kib=sum(m.storage_kib for m in mods))
    plan.steps.append(Step("record current versions for rollback", ["dpkg-query", "-W"] + sorted(installed)))
    plan.steps.append(Step("upgrade only T.A.S.K. packages from the offline bundle",
                           ["apt-get", "install", "--only-upgrade", "--no-download"] +
                           [f"./debs/{p}_*.deb" for p in _packages(mods)], root=True))
    plan.notes.append("Configuration files are kept (dpkg conffile handling); user data in your home folder is never touched.")
    plan.notes.append("Rollback: re-install the previous .deb versions recorded in step 1 (keep the old bundle).")
    return plan


def uninstall_plan(installed: dict[str, str], ids=None) -> Plan:
    if ids:
        pkgs = _packages(BY_ID[i] for i in ids)
        pkgs = [p for p in pkgs if p in installed]
    else:
        pkgs = sorted(installed)
    plan = Plan("uninstall")
    plan.steps.append(Step("remove T.A.S.K. packages, keeping configuration (no purge, no autoremove)",
                           ["apt-get", "remove"] + pkgs, root=True))
    plan.notes.append("Kept: /etc/task, ~/.config/task-*, ~/.local/share/task-*, maps, ZIM libraries and message history.")
    plan.notes.append("Shared Debian packages (Qt, Direwolf, gpsd, SoapySDR) are left installed so other apps keep working.")
    return plan


FORBIDDEN_TOKENS = ("purge", "--purge", "autoremove", "enable", "restart", "reboot", "flash", "esptool", "dd")


def assert_safe(plan: Plan) -> None:
    for s in plan.steps:
        for tok in s.argv:
            if tok in FORBIDDEN_TOKENS:
                raise AssertionError(f"forbidden token {tok!r} in step {s.description!r}")
        if s.argv and s.argv[0] in ("systemctl", "bash", "sh") :
            raise AssertionError(f"forbidden command {s.argv[0]!r}")
