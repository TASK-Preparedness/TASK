# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Optional user file ``~/.config/task-launcher/reference.toml`` (new in 0.2.0, read-only for the
launcher, never created by it)::

    [medical]
    dirs = ["/home/op/Documents/medical"]     # folders with offline PDFs / HTML

    [weather]
    dirs = ["/home/op/wx"]                    # folders where decoders write images / logs
"""

import tomllib

from task_launcher import paths


def load(path=None):
    path = path or (paths.config_dir() / "reference.toml")
    try:
        with open(path, "rb") as fh:
            doc = tomllib.load(fh)
    except FileNotFoundError:
        return {}, ""
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return {}, f"{path}: {exc}"
    return (doc if isinstance(doc, dict) else {}), ""


def dirs(section: str, doc: dict):
    sec = doc.get(section, {})
    vals = sec.get("dirs", []) if isinstance(sec, dict) else []
    return [v for v in vals if isinstance(v, str) and v.startswith("/")][:16]
