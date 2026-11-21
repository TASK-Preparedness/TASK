# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""The Phase 4C rain->task rebrand as a pure function, so the Phase 1/2 freeze tests can check that
frozen files differ from the accepted tree ONLY by this mechanical rename. Account/group names stay
(migration stage M4); deploy/ legacy installer files are not renamed."""
import pathlib
PROTECT = [
    ('grp.getgrnam("rain-core")', "@@A1@@"), ('SERVICE_USER = "rain-core"', "@@A2@@"),
    ('SERVICE_GROUP = "rain-core"', "@@A3@@"), ("group rain-core", "@@A4@@"),
    ('b"rain-dummy-salt!"', "@@A5@@"), ("group rain-core does not exist", "@@A6@@"),
    ("could not set socket group rain-core", "@@A7@@"),
]
RULES = [("rain_core", "task_core"), ("rain_console", "task_console"), ("RainCoreError", "TaskCoreError"),
         ("rain-core-admin", "task-core-admin"), ("rain-console", "task-console"), ("rain-smoke", "task-smoke"),
         ("/etc/rain/", "/etc/task/"), ("/etc/rain", "/etc/task"), ("/var/lib/rain", "/var/lib/task"),
         ("/run/rain/", "/run/task/"), ("/usr/lib/rain", "/usr/lib/task-core"), ("rain-core", "task-core"),
         ("R.A.I.N.", "T.A.S.K."), ('"rain-', '"task-'), ("Remote Access Information Network", "Tactical Access Support Kit")]
PATH_RULES = [("rain_core/", "task_core/"), ("console/rain_console/", "console/task_console/"),
              ("console/share/rain-console", "console/share/task-console"),
              ("console/share/icons/hicolor/scalable/apps/rain-console", "console/share/icons/hicolor/scalable/apps/task-console")]


def rebrand_text(t: str) -> str:
    for a, b in PROTECT:
        t = t.replace(a, b)
    for a, b in RULES:
        t = t.replace(a, b)
    for a, b in PROTECT:
        t = t.replace(b, a)
    return t


def rebrand_path(name: str) -> str:
    if name.startswith("deploy/"):
        return name
    for a, b in PATH_RULES:
        if name.startswith(a):
            return b + name[len(a):]
    return name
