# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Load T.A.S.K. Resources' embeddable browser in-process (Phase 4F.3).

task-resources (Debian package) keeps its modules in /usr/share/task-resources; the launcher imports them from
there (no exec, no second process). Requires task-resources >= 0.2.2 (read-only Index + ui.browser).
"""

import os
import sys

RES_PATH = "/usr/share/task-resources"
MIN_VERSION = (0, 2, 2)


class EmbedUnavailable(Exception):
    pass


def _path():
    return os.environ.get("TASK_RESOURCES_PYPATH") or RES_PATH


def load():
    """-> the task_resources package (with .ui.browser, .library, .classify imported) or EmbedUnavailable."""
    p = _path()
    if os.path.isdir(p) and p not in sys.path:
        sys.path.append(p)
    try:
        import task_resources
        ver = tuple(int(x) for x in task_resources.__version__.split(".")[:3])
    except (ImportError, ValueError) as exc:
        raise EmbedUnavailable(f"T.A.S.K. Resources is not installed ({type(exc).__name__}); install "
                               "task-resources 0.2.2 or newer") from None
    if ver < MIN_VERSION:
        raise EmbedUnavailable(f"T.A.S.K. Resources {task_resources.__version__} is too old for the embedded "
                               "Medical reader; install task-resources 0.2.2 or newer")
    try:
        import task_resources.classify  # noqa: F401
        import task_resources.library  # noqa: F401
        import task_resources.ui.browser  # noqa: F401
    except Exception as exc:  # noqa: BLE001 - e.g. python3-libzim missing
        raise EmbedUnavailable(f"T.A.S.K. Resources reader could not load: {exc}") from None
    return task_resources


def prepare_before_qapplication():
    """Register the zim/epub schemes for the WebEngine reader; must run before QApplication. Best effort."""
    try:
        load()
        from task_resources import settings as sm, viewer
        return viewer.prepare_before_qapplication(sm.load().viewer)
    except Exception:  # noqa: BLE001 - the lightweight reader still works
        return "lightweight"


def engine(guard=None):
    """WebEngine only if its schemes were registered before QApplication; otherwise the lightweight reader.
    (A known-crashing configuration is handled by the reader itself: guarded fallback + manual retry.)"""
    try:
        from task_resources import settings as sm, viewer
        eng, _ = viewer.choose(sm.load().viewer)
        if eng == "webengine":
            from task_resources.viewer import web
            if not web._registered:
                return "lightweight"
        return eng
    except Exception:  # noqa: BLE001
        return "lightweight"


GUARD_FILE = "medical-webengine-guard.json"


def make_guard():
    """task-resources >= 0.2.4: WebEngine crash guard for the embedded reader (marker in the launcher's own state
    dir, ~/.local/state/task-launcher/, 0600). None with older task-resources (no guard, behaviour unchanged)."""
    try:
        from task_resources.viewer.guard import CrashGuard
    except ImportError:
        return None
    from task_launcher import __version__, paths
    try:
        return CrashGuard(paths.state_dir() / GUARD_FILE, host=f"task-launcher {__version__}")
    except Exception:  # noqa: BLE001 - the guard must never stop the reader from opening
        return None
