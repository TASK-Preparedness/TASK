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
* fully-offline installs use only local .deb files. Each apt step is preceded by a read-only
  `apt-get install --print-uris` check that must list only local ``file:`` URIs, so the plan
  stops before anything would be downloaded. (`--no-download` cannot be used: apt 3.0.4 in Debian 13
  aborts with "Internal Error, Pathname to install is not absolute" whenever it is combined with
  local .deb arguments; found in the Milestone B arm64 chroot test.)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .catalog import BY_ID, Module, installable, resolve
from .compat import Verdict

BACKUP_DIR = "~/task-backups/installer-<timestamp>"   # expanded by the (future) executor, user-owned

COMPLETE, CUSTOM, MINIMAL = "complete", "custom", "minimal"
SOURCE_OFFLINE, SOURCE_ONLINE = "offline", "online"


@dataclass
class Step:
    description: str
    argv: list[str]
    root: bool = False
    network: bool = False
    expect: str = ""          # "local-uris-only": stdout of this check must list only file: URIs


LOCAL_URIS_ONLY = "local-uris-only"


def check_local_uris(stdout: str) -> list[str]:
    """Return the non-local URIs in `apt-get --print-uris` output (empty list = nothing to download)."""
    bad = []
    for ln in stdout.splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("'file:"):
            bad.append(ln.split()[0].strip("'"))
    return bad


def _offline_apt(description: str, opts: list[str], files: list[str]) -> list[Step]:
    return [Step("check that nothing would be downloaded (read-only, must list only local files)",
                 ["apt-get", "install", "--print-uris", "-qq"] + opts + files, expect=LOCAL_URIS_ONLY),
            Step(description, ["apt-get", "install"] + opts + files, root=True)]


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


def _deb_paths(pkgs, bundle, deb_dir):
    d = deb_dir or (str(bundle.directory) if bundle is not None else "./debs")
    if bundle is not None:
        files = [bundle.packages[p].file for p in pkgs]
    else:
        files = [f"{p}_*.deb" for p in pkgs]
    # apt treats an argument as a local file only if it contains a slash
    return [(d.rstrip("/") + "/" + f) if d not in ("", ".") else "./" + f for f in files]


def _preflight_steps(plan: Plan, preflight) -> None:
    if preflight is None:
        return
    plan.notes.extend(f"Preflight: {w}" for w in preflight.warnings)
    if preflight.modified_files:
        plan.steps.append(Step("back up locally modified package files before they can be overwritten",
                               ["cp", "-a", "--parents"] + list(preflight.modified_files) + [BACKUP_DIR]))
    installed = sorted(set(preflight.upgrades) | set(preflight.reinstalls))
    if installed:
        plan.steps.append(Step("record installed T.A.S.K. versions for rollback (read-only)", ["dpkg-query", "-W"] + installed))


def install_plan(mods, verdict: Verdict, source: str = SOURCE_OFFLINE, deb_dir: str | None = None,
                 bundle=None, preflight=None) -> Plan:
    if preflight is not None and not preflight.ok:
        raise PermissionError("preflight found blockers: " + "; ".join(preflight.blockers))
    pkgs = _packages(mods)
    plan = Plan("install", list(mods), storage_kib=sum(m.storage_kib for m in mods))
    no_rec = verdict.profile == "no-webengine"
    if source == SOURCE_OFFLINE:
        plan.steps.append(Step("verify the offline bundle checksums", ["sha256sum", "-c", "SHA256SUMS"]))
        _preflight_steps(plan, preflight)
        plan.steps.extend(_offline_apt("install T.A.S.K. packages from local files only",
                                       ["--no-install-recommends"] if no_rec else [], _deb_paths(pkgs, bundle, deb_dir)))
        if bundle is None:
            plan.notes.append("No bundle manifest given: the file names shown are illustrative globs.")
        plan.notes.append("Debian dependencies (Qt, numpy, ...) must already be installed or be in the local apt "
                          "cache; a full offline dependency bundle is Milestone D.")
    else:
        plan.network_required = True
        _preflight_steps(plan, preflight)
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


def repair_plan(installed: dict[str, str], bundle=None, preflight=None) -> Plan:
    pkgs = sorted(installed)
    plan = Plan("repair")
    plan.steps.append(Step("check installed files against package checksums (read-only)", ["dpkg", "--verify"] + pkgs))
    if preflight is not None and preflight.modified_files:
        plan.steps.append(Step("back up locally modified package files before re-installing",
                               ["cp", "-a", "--parents"] + list(preflight.modified_files) + [BACKUP_DIR]))
    if bundle is not None:
        same = [p for p in pkgs if p in bundle.packages and bundle.packages[p].version == installed[p]]
        missing = [p for p in pkgs if p not in same]
        files = _deb_paths(same, bundle, None)
        if missing:
            plan.notes.append("Not repairable from this bundle (different or missing version): " + ", ".join(missing))
    else:
        files = [f"./debs/{p}_{v}_*.deb" for p, v in sorted(installed.items())]
    plan.steps.extend(_offline_apt("re-install the same versions from the offline bundle", ["--reinstall"], files))
    plan.notes.append("dpkg --verify will list intentional local edits (e.g. a hand-modified notifier); review before re-installing, "
                      "because re-installing overwrites changed package files. Back them up first.")
    return plan


def update_plan(installed: dict[str, str], mods, bundle=None, preflight=None) -> Plan:
    if preflight is not None and not preflight.ok:
        raise PermissionError("preflight found blockers: " + "; ".join(preflight.blockers))
    plan = Plan("update", list(mods), storage_kib=sum(m.storage_kib for m in mods))
    plan.steps.append(Step("record current versions for rollback", ["dpkg-query", "-W"] + sorted(installed)))
    if preflight is not None:
        plan.notes.extend(f"Preflight: {w}" for w in preflight.warnings)
        if preflight.modified_files:
            plan.steps.append(Step("back up locally modified package files before they can be overwritten",
                                   ["cp", "-a", "--parents"] + list(preflight.modified_files) + [BACKUP_DIR]))
    pkgs = [p for p in _packages(mods) if p in installed]
    plan.steps.extend(_offline_apt("upgrade only T.A.S.K. packages from the offline bundle", ["--only-upgrade"],
                                   _deb_paths(pkgs, bundle, None)))
    plan.notes.append("A running task-mesh-service keeps the old code until you restart it yourself; "
                      "the installer never restarts services.")
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


def recovery_plan(installed: dict[str, str], previous_bundle=None, backup_dir: str = BACKUP_DIR) -> Plan:
    """Return to the versions recorded before an update, from the previous (kept) bundle, and restore
    backed-up local modifications. Nothing is purged; configuration and user data are untouched."""
    plan = Plan("recovery")
    pkgs = sorted(installed)
    plan.steps.append(Step("show what is installed now (read-only)", ["dpkg-query", "-W"] + pkgs))
    plan.steps.append(Step("check installed files (read-only)", ["dpkg", "--verify"] + pkgs))
    if previous_bundle is not None:
        keep = [p for p in pkgs if p in previous_bundle.packages]
        files = _deb_paths(keep, previous_bundle, None)
    else:
        files = [f"./previous-debs/{p}_{v}_all.deb" for p, v in sorted(installed.items())]
    plan.steps.extend(_offline_apt("re-install the previously recorded versions from local files",
                                   ["--allow-downgrades"], files))
    plan.steps.append(Step("restore backed-up local modifications (review the backup first)",
                           ["cp", "-a", "--no-preserve=ownership", backup_dir + "/usr", "/"], root=True))
    plan.notes.append("Recovery never purges, never autoremoves and never restarts services; restart task-mesh-service "
                      "yourself afterwards if it was running.")
    plan.notes.append("If the desktop does not start, the same commands work from a text console (Ctrl+Alt+F2) or SSH.")
    return plan


FORBIDDEN_TOKENS = ("purge", "--purge", "autoremove", "enable", "restart", "reboot", "flash", "esptool", "dd")


def assert_safe(plan: Plan) -> None:
    for s in plan.steps:
        for tok in s.argv:
            if tok in FORBIDDEN_TOKENS:
                raise AssertionError(f"forbidden token {tok!r} in step {s.description!r}")
            if tok.startswith("--force") or tok in ("--allow-remove-essential", "--allow-change-held-packages"):
                raise AssertionError(f"forbidden option {tok!r} in step {s.description!r}")
        if s.argv and s.argv[0] in FORBIDDEN_COMMANDS:
            raise AssertionError(f"forbidden command {s.argv[0]!r}")


FORBIDDEN_COMMANDS = ("systemctl", "bash", "sh", "pip", "pip3", "python3", "usermod", "useradd", "rm", "dd",
                      "esptool", "esptool.py", "meshtastic", "rfcomm", "bluetoothctl", "reboot", "shutdown")
