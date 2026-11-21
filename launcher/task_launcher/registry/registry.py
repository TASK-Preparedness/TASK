# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""The app registry: manifest apps (incl. built-in handlers) and user-added desktop applications
in one list of tiles. Tile source types: ``builtin`` | ``manifest`` | ``desktop``.

Static status (computed here): Available (shown as "Installed" in 0.1.0), Planned, Unavailable
(reason), Disabled, Error (rejected manifest). Runtime status (Running, Error after a failed launch/crash) is overlaid by
the process manager. A tile existing never implies Installed.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from task_launcher import PLATFORM_VERSION
from task_launcher.registry import desktop as D
from task_launcher.registry.discovery import discover
from task_launcher.registry.execcheck import check_executable
from task_launcher.registry.manifest import version_tuple
from task_launcher.registry.tilestore import TileStore

FILE_MANAGERS = ("/usr/bin/pcmanfm", "/usr/bin/pcmanfm-qt", "/usr/bin/thunar", "/usr/bin/nautilus",
                 "/usr/bin/nemo", "/usr/bin/caja", "/usr/bin/dolphin")
XDG_OPEN = "/usr/bin/xdg-open"

# INSTALLED keeps its Phase 3 constant name; the value is "Available" since 0.2.0 (Phase 4A
# status vocabulary: Planned / Available / Unavailable / Running / Error, plus the per-user Disabled).
INSTALLED, PLANNED, UNAVAILABLE, DISABLED, ERROR, RUNNING, STARTING = (
    "Available", "Planned", "Unavailable", "Disabled", "Error", "Running", "Starting")
AVAILABLE = INSTALLED
# Built-ins of the approved reference that show no status line when available (Phase 3 look).
QUIET_BUILTINS = ("system", "files", "app-manager", "devices")


@dataclass
class Tile:
    key: str
    source: str                      # builtin | manifest | desktop
    name: str
    description: str = ""
    icon: object = "shapes"          # Lucide name | Path (SVG) | ("theme", name) | ("file", path)
    status: str = INSTALLED
    reason: str = ""
    version: str = ""
    manifest: object = None
    entry: object = None             # DesktopEntry for desktop tiles (None if gone)
    desktop_id: str = None
    argv: list = None                # resolved argv for exec/desktop tiles
    cwd: str = None
    builtin: str = None
    enabled: bool = True
    hidden: bool = False
    default_enabled: bool = True
    can_disable: bool = True
    can_hide: bool = True
    min_role: str = "public"
    warnings: list = field(default_factory=list)
    variant: str = ""                # label of the resolved exec candidate, e.g. "FoxtrotGPS (fallback)"
    actions: list = field(default_factory=list)   # [ResolvedAction]
    readiness: str = None            # readiness probe name (manifest ``readiness``)

    @property
    def app_id(self):
        return self.manifest.id if self.manifest else None

    @property
    def launchable(self):
        return self.status in (INSTALLED, UNAVAILABLE) and (self.builtin is not None or self.argv is not None)


@dataclass
class ResolvedAction:
    id: str
    label: str
    argv: list = None                # final argv (terminal-wrapped when needed) or None
    reason: str = ""                 # why it is unavailable


def resolve_actions(m, path_env=None):
    out = []
    for a in m.actions:
        status, reason = check_executable(a.exec[0])
        if status != "ok":
            out.append(ResolvedAction(a.id, a.label, None, reason))
            continue
        argv = list(a.exec)
        if a.terminal:
            term, flag = D.find_terminal(path_env)
            if term is None:
                out.append(ResolvedAction(a.id, a.label, None, "terminal app, but no terminal emulator is installed"))
                continue
            argv = [term] + flag + argv
        out.append(ResolvedAction(a.id, a.label, argv))
    return out


def files_opener():
    """(argv-prefix or None, description). Prefer xdg-open (the user's default), else a known file
    manager. The Files built-in falls back from a failing xdg-open to the first file manager."""
    fms = [p for p in FILE_MANAGERS if os.path.isfile(p) and os.access(p, os.X_OK)]
    if os.path.isfile(XDG_OPEN) and os.access(XDG_OPEN, os.X_OK):
        return [XDG_OPEN], "xdg-open (desktop default)", fms
    if fms:
        return [fms[0]], os.path.basename(fms[0]), fms[1:]
    return None, "", []


class Registry:
    def __init__(self, manifest_dirs=None, desktop_dirs=None, store: TileStore = None, desktops=None,
                 core_version_fn=lambda: None):
        self.manifest_dirs = manifest_dirs
        self.desktop_dirs = desktop_dirs
        self.store = store or TileStore()
        self.desktops = desktops
        self.core_version_fn = core_version_fn
        self.manifests = {}
        self.problems = []
        self.desktop_entries = {}
        self.tiles = []              # every tile incl. hidden, in display order
        self.reload_manifests()

    # -------------------------------------------------------------- loading
    def reload_manifests(self):
        self.manifests, self.problems = discover(self.manifest_dirs)

    def scan_desktop(self):
        """Blocking scan; the UI runs it in a worker thread (DesktopScanWorker) and calls set_desktop."""
        return D.scan(self.desktop_dirs)

    def set_desktop_entries(self, entries: dict):
        self.desktop_entries = entries

    # -------------------------------------------------------------- tiles
    def build(self, show_planned=True):
        tiles = {}
        default_manifest = sorted(self.manifests.values(), key=lambda m: (m.order, m.name.casefold(), m.id))
        for m in default_manifest:
            t = self._manifest_tile(m)
            tiles[t.key] = t
        for item in self.store.custom:
            t = self._desktop_tile(item)
            tiles[t.key] = t
        default_keys = [f"app:{m.id}" for m in default_manifest] + ["desktop:" + c["desktop_id"] for c in self.store.custom]
        order = self.store.arrange(default_keys)
        self.tiles = [tiles[k] for k in order if k in tiles]
        for t in self.tiles:
            t.hidden = t.key in self.store.hidden or (not show_planned and t.status == PLANNED)
        return self.visible()

    def visible(self):
        return [t for t in self.tiles if not t.hidden]

    def get(self, key):
        for t in self.tiles:
            if t.key == key:
                return t
        return None

    def _manifest_tile(self, m):
        source = "builtin" if m.builtin else "manifest"
        t = Tile(key=f"app:{m.id}", source=source, name=m.name, description=m.description, icon=m.icon,
                 version=m.version, manifest=m, builtin=m.builtin, default_enabled=m.enabled,
                 min_role=m.min_role, warnings=list(m.warnings), readiness=m.readiness)
        t.can_disable = m.builtin != "app-manager"
        t.can_hide = m.builtin != "app-manager"
        t.enabled = self.store.is_enabled(m.id, m.enabled) if t.can_disable else True
        if m.status == "planned":
            t.status, t.reason = PLANNED, (m.roadmap or "no app exists yet")
            return t
        if version_tuple(m.min_platform) > version_tuple(PLATFORM_VERSION):
            t.status, t.reason = UNAVAILABLE, f"requires launcher platform {m.min_platform}"
        elif m.core_min_version and self.core_version_fn():
            cv = version_tuple(self.core_version_fn())
            if cv is not None and cv < version_tuple(m.core_min_version):
                t.status, t.reason = UNAVAILABLE, f"requires task-core {m.core_min_version}"
        if t.status == INSTALLED:
            if m.builtin in ("devices", "radio", "library") and m.exec:
                argv, status, reason = m.resolve_exec()
                if argv:
                    t.argv = argv
                    t.variant = m.label_for(argv)
                elif m.builtin == "radio" and status == "missing":
                    t.variant = "built-in receive-only monitor"  # task-aprs not installed: builtin opens
                elif m.builtin == "library" and status == "missing":
                    t.variant = "native viewer"   # task-resources not installed: the 4A built-in window opens
                else:
                    t.status = UNAVAILABLE
                    t.reason = ("task-console not installed" if status == "missing" else reason)
            elif m.builtin == "files":
                prefix, how, _ = files_opener()
                if prefix is None:
                    t.status, t.reason = UNAVAILABLE, "no file manager found (xdg-open, pcmanfm, thunar, nautilus, …)"
            elif m.exec:
                argv, status, reason = m.resolve_exec()
                if argv:
                    t.argv = argv
                    t.variant = m.label_for(argv)
                elif status == "unsafe":
                    t.status, t.reason = ERROR, reason
                else:
                    t.status, t.reason = UNAVAILABLE, reason
        if t.status in (INSTALLED, UNAVAILABLE) and m.actions:
            t.actions = resolve_actions(m)
        if not t.enabled and t.status in (INSTALLED, UNAVAILABLE):
            t.status, t.reason = DISABLED, "disabled in App Manager"
        return t

    def _desktop_tile(self, item):
        did = item["desktop_id"]
        entry = self.desktop_entries.get(did)
        name = item.get("name") or (entry.name if entry else (item.get("label") or did))
        t = Tile(key="desktop:" + did, source="desktop", name=name[:40], desktop_id=did, entry=entry)
        if entry is not None:
            t.description = entry.comment or entry.generic_name
        t.icon = self.desktop_icon(entry, item.get("icon", ""))
        plan = D.plan_launch(entry)
        if plan.argv:
            t.argv, t.cwd = plan.argv, plan.cwd
        else:
            t.status = UNAVAILABLE if plan.status in ("missing", "unavailable") else ERROR
            t.reason = plan.problem
        return t

    @staticmethod
    def desktop_icon(entry, override=""):
        value = override or (entry.icon if entry else "")
        if not value:
            return "app-window" if (Path(__file__).parent.parent / "data/icons/lucide/app-window.svg").exists() else "shapes"
        if value.startswith("/"):
            return ("file", value) if D.icon_file_ok(value) else "shapes"
        if "/" in value or len(value) > 255:
            return "shapes"
        return ("theme", value)

    # -------------------------------------------------------------- mutations
    def add_desktop(self, desktop_id):
        if desktop_id not in self.desktop_entries:
            raise KeyError(f"unknown desktop-file id {desktop_id}")
        return self.store.add_desktop(desktop_id, self.desktop_entries[desktop_id].name)

    def remove_tile(self, key):
        """Custom tile: forget it. Manifest tile: hide it from the dashboard. Never uninstalls anything."""
        if key.startswith("desktop:"):
            return self.store.remove_desktop(key.split(":", 1)[1])
        self.store.set_hidden(key, True)
        return True

    def set_enabled(self, tile, enabled):
        if not tile.manifest or not tile.can_disable:
            raise ValueError("this app cannot be disabled")
        self.store.set_enabled(tile.manifest.id, enabled, tile.default_enabled)

    def move(self, key, delta):
        order = [t.key for t in self.tiles if not t.hidden]
        new_visible = self.store.move(order, key, delta)
        hidden_keys = [t.key for t in self.tiles if t.hidden]
        self.store.order = new_visible + [k for k in self.store.order if k not in new_visible]
        for k in hidden_keys:
            if k not in self.store.order:
                self.store.order.append(k)
        self.store.save()
        return new_visible
