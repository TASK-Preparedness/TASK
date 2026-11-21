# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Per-user dashboard layout and customisations: ~/.config/task-launcher/tiles.json.

Versioned schema (``schema: 1``), atomic writes, never in task-core configuration.

* ``order``: tile keys in display order (``app:<manifest id>`` or ``desktop:<desktop-file id>``).
  Keys not listed are placed by the default rule: manifest tiles by manifest ``order`` then
  name, desktop tiles after them in the order they were added.
* ``hidden``: manifest tiles the user removed from the dashboard (App Manager can show them
  again). App Manager itself cannot be hidden (it is the way back).
* ``custom``: desktop applications the user added: ``{"desktop_id", "name", "icon"}``;
  ``name``/``icon`` are launcher-side overrides ('' = use the desktop file's). The .desktop file
  is never modified.
* ``enabled``: per-user enable/disable overrides for manifest apps ``{id: bool}``.
"""

import re

from task_launcher import atomic, paths

SCHEMA = 1
FILE_NAME = "tiles.json"
MAX_CUSTOM = 200
MAX_NAME = 40
UNHIDEABLE = {"app:task.app-manager"}
# Phase 4C: manifest ids were renamed rain.* -> task.*; saved layouts keep working.
LEGACY_ID_PREFIX, ID_PREFIX = "rain.", "task."


def migrate_id(mid):
    return ID_PREFIX + mid[len(LEGACY_ID_PREFIX):] if isinstance(mid, str) and mid.startswith(LEGACY_ID_PREFIX) else mid


def migrate_key(key):
    if isinstance(key, str) and key.startswith("app:"):
        return "app:" + migrate_id(key[4:])
    return key
KEY_RE = re.compile(r"^(app|desktop):[A-Za-z0-9._\-]{1,255}$")


def store_path():
    return paths.config_dir() / FILE_NAME


class TileStore:
    def __init__(self, path=None):
        self.path = path or store_path()
        self.order = []
        self.hidden = set()
        self.custom = []        # list of dicts, in the order added
        self.enabled = {}
        self.load_problem = ""
        self.load()

    # -------------------------------------------------------------- persistence
    def load(self):
        doc = atomic.read_json(self.path)
        self.order, self.hidden, self.custom, self.enabled = [], set(), [], {}
        if doc is None:
            if self.path.exists():
                self.load_problem = "tiles.json unreadable or invalid; using the default layout"
            return
        if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
            self.load_problem = "tiles.json has an unsupported schema; using the default layout"
            return
        order = doc.get("order", [])
        if isinstance(order, list):
            order = [migrate_key(k) for k in order]
            seen = set()
            for k in order:
                if isinstance(k, str) and KEY_RE.match(k) and k not in seen:
                    seen.add(k)
                    self.order.append(k)
        hidden = doc.get("hidden", [])
        if isinstance(hidden, list):
            hidden = [migrate_key(k) for k in hidden]
            self.hidden = {k for k in hidden if isinstance(k, str) and KEY_RE.match(k) and k not in UNHIDEABLE}
        custom = doc.get("custom", [])
        if isinstance(custom, list):
            seen = set()
            for item in custom[:MAX_CUSTOM]:
                if not isinstance(item, dict):
                    continue
                did = item.get("desktop_id")
                if not isinstance(did, str) or not KEY_RE.match("desktop:" + did) or did in seen:
                    continue
                seen.add(did)
                name = item.get("name") if isinstance(item.get("name"), str) else ""
                icon = item.get("icon") if isinstance(item.get("icon"), str) else ""
                label = item.get("label") if isinstance(item.get("label"), str) else ""
                self.custom.append({"desktop_id": did, "name": name[:MAX_NAME], "icon": icon[:4096],
                                    "label": label[:MAX_NAME]})
        enabled = doc.get("enabled", {})
        if isinstance(enabled, dict):
            self.enabled = {migrate_id(k): v for k, v in enabled.items() if isinstance(k, str) and isinstance(v, bool)}

    def save(self):
        atomic.write_json(self.path, {
            "schema": SCHEMA,
            "order": list(self.order),
            "hidden": sorted(self.hidden),
            "custom": list(self.custom),
            "enabled": dict(sorted(self.enabled.items())),
        })

    # -------------------------------------------------------------- custom tiles
    def custom_for(self, desktop_id):
        for item in self.custom:
            if item["desktop_id"] == desktop_id:
                return item
        return None

    def add_desktop(self, desktop_id: str, label: str = "") -> str:
        key = "desktop:" + desktop_id
        if not KEY_RE.match(key):
            raise ValueError("invalid desktop-file id")
        if self.custom_for(desktop_id) is not None:
            return key
        if len(self.custom) >= MAX_CUSTOM:
            raise ValueError(f"at most {MAX_CUSTOM} custom tiles")
        # label: the application's name when it was added, shown if the app is later uninstalled
        self.custom.append({"desktop_id": desktop_id, "name": "", "icon": "", "label": (label or "")[:MAX_NAME]})
        if self.order and key not in self.order:
            self.order.append(key)
        self.save()
        return key

    def remove_desktop(self, desktop_id: str) -> bool:
        item = self.custom_for(desktop_id)
        if item is None:
            return False
        self.custom.remove(item)
        key = "desktop:" + desktop_id
        if key in self.order:
            self.order.remove(key)
        self.save()
        return True

    def rename(self, desktop_id: str, name: str):
        item = self.custom_for(desktop_id)
        if item is None:
            raise KeyError(desktop_id)
        name = " ".join((name or "").split())
        if len(name) > MAX_NAME:
            raise ValueError(f"names are at most {MAX_NAME} characters")
        item["name"] = name
        self.save()

    def set_icon(self, desktop_id: str, icon: str):
        item = self.custom_for(desktop_id)
        if item is None:
            raise KeyError(desktop_id)
        item["icon"] = icon or ""
        self.save()

    # -------------------------------------------------------------- visibility / enable
    def set_hidden(self, key: str, hidden: bool):
        if key in UNHIDEABLE and hidden:
            raise ValueError("App Manager cannot be removed from the dashboard")
        (self.hidden.add if hidden else self.hidden.discard)(key)
        self.save()

    def set_enabled(self, app_id: str, enabled: bool, default: bool):
        if enabled == default:
            self.enabled.pop(app_id, None)
        else:
            self.enabled[app_id] = enabled
        self.save()

    def is_enabled(self, app_id: str, default: bool) -> bool:
        return self.enabled.get(app_id, default)

    # -------------------------------------------------------------- order
    def arrange(self, default_keys):
        """Return the display order for the given visible keys (default order first)."""
        listed = [k for k in self.order if k in default_keys]
        rest = [k for k in default_keys if k not in listed]
        if not self.order:
            return list(default_keys)
        # unlisted keys keep their default relative position: insert after their default predecessor
        result = list(listed)
        for k in rest:
            idx = default_keys.index(k)
            anchor = None
            for prev in reversed(default_keys[:idx]):
                if prev in result:
                    anchor = prev
                    break
            result.insert(result.index(anchor) + 1 if anchor else 0, k)
        return result

    def move(self, current_order, key, delta: int) -> list:
        """Move ``key`` by ``delta`` positions in ``current_order`` (clamped), persist, return new order."""
        order = list(current_order)
        if key not in order:
            return order
        i = order.index(key)
        j = max(0, min(len(order) - 1, i + delta))
        if i == j:
            return order
        order.insert(j, order.pop(i))
        self.order = order + [k for k in self.order if k not in order]
        self.save()
        return order

    def reset_layout(self):
        """Default order, all built-ins shown again. Custom tiles stay (appended, in the order added)."""
        self.order = []
        self.hidden = set()
        self.save()
