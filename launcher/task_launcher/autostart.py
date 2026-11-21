# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Optional per-user autostart: ~/.config/autostart/task-launcher.desktop (XDG autostart).

Off by default. Enabling writes exactly that one file; disabling removes it, but only if it is
the file this launcher wrote (marker key), so a hand-made entry is never deleted. No system file,
no labwc/session/display-manager change. Whether the session runs XDG autostart entries depends
on the desktop (on labwc this is UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST).
"""

from task_launcher import atomic, paths

FILE_NAME = "task-launcher.desktop"
MARKER = "X-TaskLauncher-Autostart=true"
EXEC = "/usr/bin/task-launcher"


def autostart_path():
    return paths.autostart_dir() / FILE_NAME


def content(title: str = "T.A.S.K.") -> str:
    return (
        "# SPDX-License-Identifier: GPL-3.0-or-later\n"
        "# SPDX-FileCopyrightText: 2026 Joshua Sturtz\n"
        "# Written by task-launcher Settings -> 'Start when I log in'. Untick it there (or delete\n"
        "# this file) to undo. Per-user only.\n"
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={title} launcher\n"
        f"Exec={EXEC}\n"
        "Icon=task-launcher\n"
        "Terminal=false\n"
        "NoDisplay=false\n"
        f"{MARKER}\n"
    )


def is_enabled() -> bool:
    try:
        return MARKER in autostart_path().read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False


def foreign_entry_exists() -> bool:
    p = autostart_path()
    return p.exists() and not is_enabled()


def enable(title: str = "T.A.S.K.") -> None:
    if foreign_entry_exists():
        raise FileExistsError(f"{autostart_path()} exists and was not written by task-launcher")
    atomic.write_bytes(autostart_path(), content(title).encode("utf-8"), mode=0o644)


def disable() -> bool:
    """Remove our entry. Returns True if a file was removed."""
    if not is_enabled():
        return False
    autostart_path().unlink()
    return True
