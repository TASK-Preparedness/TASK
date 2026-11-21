# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Behaviour common to both viewers; Qt widgets mix this in."""

from task_resources.viewer import urls
from task_resources.viewer.nav import Location, Navigator
from task_resources.zim.archive import ZimError


class ViewerMixin:
    name = "base"

    def _init_viewer(self, library):
        self.library = library
        self.nav = Navigator()
        self.blocked = []           # external URLs refused (never fetched/opened)
        self.last_error = ""
        self.last_title = ""
        self.listeners = []         # callables(event, **data): "navigated", "blocked", "error"

    def _emit(self, event, **data):
        for fn in list(self.listeners):
            fn(event, **data)

    # public API --------------------------------------------------------------------------
    def open(self, rid, path=None, fragment="", record=True):
        try:
            src = self.library.source(rid)
            path = path or src.main_path()
            if path is None:
                raise ZimError("this resource has no main page")
            final, chain = src.resolve(path)
        except Exception as exc:  # noqa: BLE001 - every failure is shown, never raised into Qt
            self.last_error = str(exc) or type(exc).__name__
            self._show_error(self.last_error)
            self._emit("error", message=self.last_error)
            return False
        loc = Location(rid, final, fragment)
        if record:
            self.nav.go(loc)
        self._render(src, loc)
        try:
            self.library.index.add_history(rid, final, self.last_title)
        except Exception:  # noqa: BLE001 - history is best effort
            pass
        self._emit("navigated", rid=rid, path=final, title=self.last_title, redirected_from=chain)
        return True

    def open_url(self, url, record=True):
        p = urls.parse(url)
        if p is None:
            self.blocked.append(str(url))
            self._emit("blocked", url=str(url))
            return False
        _, rid, path, frag = p
        if self.nav.current and rid == self.nav.current.rid and path == self.nav.current.path and frag:
            self._scroll_to(frag)
            return True
        return self.open(rid, path, frag, record=record)

    def back(self):
        loc = self.nav.back()
        return loc is not None and self.open(loc.rid, loc.path, loc.fragment, record=False)

    def forward(self):
        loc = self.nav.forward()
        return loc is not None and self.open(loc.rid, loc.path, loc.fragment, record=False)

    def home(self):
        if self.nav.current:
            return self.open(self.nav.current.rid)
        return False
