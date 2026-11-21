# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Viewer selection: Settings.viewer = auto | webengine | lightweight, automatic fallback."""

import importlib

CHOICES = ("auto", "webengine", "lightweight")
_web = None


def webengine_available():
    global _web
    if _web is None:
        try:
            importlib.import_module("PySide6.QtWebEngineCore")
            importlib.import_module("PySide6.QtWebEngineWidgets")
            _web = (True, "")
        except (ImportError, OSError) as exc:
            _web = (False, f"Qt WebEngine is not installed ({type(exc).__name__}); "
                           "install python3-pyside6.qtwebenginewidgets to use it")
    return _web


def choose(setting):
    """-> (engine, note). Never fails: falls back to the lightweight viewer."""
    setting = setting if setting in CHOICES else "auto"
    ok, why = webengine_available()
    if setting == "lightweight":
        return "lightweight", ""
    if ok:
        return "webengine", ""
    if setting == "webengine":
        return "lightweight", "WebEngine viewer selected but unavailable: using the lightweight viewer. " + why
    return "lightweight", ""


def prepare_before_qapplication(setting):
    """Register the zim/epub/local schemes if WebEngine might be used (must precede QApplication)."""
    engine, _ = choose(setting)
    if webengine_available()[0]:
        from task_resources.viewer.web import register_schemes
        register_schemes()
    return engine


def choose_guarded(setting, guard=None):
    """choose() plus the 0.2.4 crash guard: a configuration known to have crashed the host is not used
    automatically (-> lightweight, note). The user can still try it explicitly ("Try enhanced reader")."""
    engine, note = choose(setting)
    if engine == "webengine" and guard is not None and guard.known_crash():
        return "lightweight", ("Using the lightweight reader: " + guard.describe() + ". It is not retried "
                               "automatically; use \"Try enhanced reader\" to try again.")
    return engine, note


def make_viewer(engine, library, parent=None, guard=None):
    if engine == "webengine" and webengine_available()[0]:
        from task_resources.viewer.web import WebViewer
        return WebViewer(library, parent, guard=guard)
    from task_resources.viewer.light import LightViewer
    return LightViewer(library, parent)
