# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Branding presets. Phase 4C: T.A.S.K. is the name everywhere; the former "rain" preset is a
legacy alias that resolves to T.A.S.K. (saved settings stay valid). A custom text is possible:

* per user: Settings -> Branding (stored in ~/.config/task-launcher/settings.json);
* system default: optional /etc/task-launcher/branding.toml with keys ``preset`` and, for
  ``preset = "custom"``, ``title`` and ``subtitle``. A user choice overrides it.
"""

import tomllib

from task_launcher import paths

PRESETS = {
    "task": ("T.A.S.K.", "Tactical Access Support Kit"),
}
LEGACY_ALIASES = {"rain": "task"}
MAX_TITLE = 24
MAX_SUBTITLE = 60


def _clean(text, limit):
    if not isinstance(text, str):
        return ""
    text = " ".join(text.split())
    return text[:limit]


def system_default(path=None):
    """(preset, title, subtitle) from /etc/task-launcher/branding.toml, or None."""
    path = path or paths.SYSTEM_BRANDING_FILE
    try:
        if path.stat().st_size > 4096:
            return None
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    preset = LEGACY_ALIASES.get(doc.get("preset"), doc.get("preset"))
    if preset not in ("task", "custom"):
        return None
    return preset, _clean(doc.get("title"), MAX_TITLE), _clean(doc.get("subtitle"), MAX_SUBTITLE)


def resolve(preset, title="", subtitle="", system=None):
    """Return (title, subtitle). Unknown preset -> system default -> T.A.S.K."""
    preset = LEGACY_ALIASES.get(preset, preset)
    if preset not in ("task", "custom"):
        sysdef = system if system is not None else system_default()
        if sysdef:
            preset, title, subtitle = sysdef
        else:
            preset = "task"
    if preset == "custom":
        t, s = _clean(title, MAX_TITLE), _clean(subtitle, MAX_SUBTITLE)
        if t:
            return t, s
        preset = "task"
    return PRESETS[preset]
