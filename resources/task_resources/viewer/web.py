# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Optional Qt WebEngine viewer. Content is served by a QWebEngineUrlSchemeHandler that reads from our
libzim / EPUB / local-file layer (zim://, epub://, local://). There is no HTTP server.

Every request with any other scheme (http, https, ws, file, ftp, ...) is blocked by a request interceptor
and recorded; nothing is fetched from the network. The profile is off-the-record: no disk cache, no
persistent cookies. JavaScript inside ZIM pages runs, but it cannot reach the network.

register_schemes() must be called before the QApplication is created (Qt requirement)."""

import time

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QUrl
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineSettings,
                                     QWebEngineUrlRequestInterceptor, QWebEngineUrlRequestJob,
                                     QWebEngineUrlScheme, QWebEngineUrlSchemeHandler)
from PySide6.QtWebEngineWidgets import QWebEngineView

from task_resources.viewer import urls
from task_resources.viewer.base import ViewerMixin
from task_resources.zim.archive import EntryNotFound

ALLOWED = set(urls.SCHEMES) | {"data", "blob", "about"}
_registered = False


def register_schemes():
    global _registered
    if _registered:
        return
    for name in urls.SCHEMES:
        s = QWebEngineUrlScheme(name.encode())
        s.setSyntax(QWebEngineUrlScheme.Syntax.Host)
        s.setFlags(QWebEngineUrlScheme.Flag.SecureScheme | QWebEngineUrlScheme.Flag.LocalScheme
                   | QWebEngineUrlScheme.Flag.LocalAccessAllowed | QWebEngineUrlScheme.Flag.CorsEnabled)
        QWebEngineUrlScheme.registerScheme(s)
    _registered = True


class SchemeHandler(QWebEngineUrlSchemeHandler):
    def __init__(self, library, parent=None):
        super().__init__(parent)
        self.library = library
        self.served = []

    def requestStarted(self, job: QWebEngineUrlRequestJob):
        p = urls.parse(job.requestUrl().toString())
        if p is None:
            job.fail(QWebEngineUrlRequestJob.Error.UrlInvalid)
            return
        scheme, rid, path, _ = p
        try:
            src = self.library.source(rid)
            final, chain = src.resolve(path)
            if chain or final != path:
                job.redirect(QUrl(urls.make(scheme, rid, final)))
                return
            c = src.get(final)
        except EntryNotFound:
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        except Exception:  # noqa: BLE001 - corrupt entry, too large, closed archive ...
            job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)
            return
        self.served.append(final)
        buf = QBuffer(job)
        buf.setData(QByteArray(c.data))
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        job.reply(c.mimetype.split(";")[0].strip().encode() or b"application/octet-stream", buf)


class NetworkBlocker(QWebEngineUrlRequestInterceptor):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.blocked = []

    def interceptRequest(self, info):
        url = info.requestUrl()
        if url.scheme().lower() not in ALLOWED:
            self.blocked.append(url.toString())
            info.block(True)


class _Page(QWebEnginePage):
    def __init__(self, profile, viewer):
        super().__init__(profile, viewer)
        self.viewer = viewer

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        s = url.toString()
        if urls.parse(s) is None:
            if url.scheme() in ("about", "data") and not is_main_frame:
                return True
            self.viewer.blocked.append(s)
            self.viewer._emit("blocked", url=s)
            return False
        if is_main_frame and nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            # WebEngine performs the load itself; we only record it in our own history
            return self.viewer._link_followed(s)
        return True

    def javaScriptConsoleMessage(self, level, message, line, source):
        self.viewer.console.append(message)

    def createWindow(self, _type):
        return None          # no pop-ups / new windows


_profile = None


def _shared_profile(library):
    """One off-the-record profile per process (Qt requires pages to die before their profile, so the
    profile lives until exit). The scheme handler always reads through the current library."""
    global _profile
    if _profile is None:
        prof = QWebEngineProfile()                 # no storage name -> off-the-record
        prof.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        prof.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        handler = SchemeHandler(library, prof)
        for name in urls.SCHEMES:
            prof.installUrlSchemeHandler(name.encode(), handler)
        blocker = NetworkBlocker(prof)
        prof.setUrlRequestInterceptor(blocker)
        _profile = (prof, handler, blocker)
    _profile[1].library = library
    return _profile


class WebViewer(ViewerMixin, QWebEngineView):
    name = "webengine"

    def __init__(self, library, parent=None, guard=None):
        QWebEngineView.__init__(self, parent)
        self._init_viewer(library)
        self.guard = guard                # 0.2.4 crash guard (armed before the first load, cleared after success)
        self._guard_done = guard is None
        self.console = []
        self.profile, self.handler, self.blocker = _shared_profile(library)
        self._blocked_start = len(self.blocker.blocked)
        self._served_start = len(self.handler.served)
        page = _Page(self.profile, self)
        st = page.settings()
        A = QWebEngineSettings.WebAttribute
        for attr, on in ((A.JavascriptEnabled, True), (A.LocalContentCanAccessRemoteUrls, False),
                         (A.LocalContentCanAccessFileUrls, False), (A.PluginsEnabled, False),
                         (A.JavascriptCanOpenWindows, False), (A.AutoLoadIconsForPage, False),
                         (A.DnsPrefetchEnabled, False), (A.PdfViewerEnabled, False),
                         (A.XSSAuditingEnabled, True)):
            st.setAttribute(attr, on)
        page.featurePermissionRequested.connect(
            lambda origin, feature: page.setFeaturePermission(
                origin, feature, QWebEnginePage.PermissionPolicy.PermissionDeniedByUser))
        self.setPage(page)
        self.loaded = None
        self.loadFinished.connect(self._done)

    def _done(self, ok):
        self.loaded = (ok, time.monotonic(), self.page().url().toString())
        if ok and not self._guard_done:
            self._guard_done = True
            self.guard.disarm()
        self.last_title = self.page().title()

    def _link_followed(self, url):
        from task_resources.viewer.nav import Location
        _, rid, path, frag = urls.parse(url)
        try:
            final, chain = self.library.source(rid).resolve(path)
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            self._emit("error", message=self.last_error)
            return True          # the scheme handler answers 404; the page shows the error
        self.nav.go(Location(rid, final, frag))
        try:
            self.library.index.add_history(rid, final, "")
        except Exception:  # noqa: BLE001
            pass
        self._emit("navigated", rid=rid, path=final, title="", redirected_from=chain)
        return True

    def _scroll_to(self, frag):
        u = QUrl(self.url())
        u.setFragment(frag)
        self.setUrl(u)

    def _show_error(self, msg):
        import html
        self.setHtml(f"<h3>Cannot show this page</h3><p>{html.escape(msg)}</p>")

    def _render(self, src, loc):
        self.loaded = None
        c_title = ""
        try:
            c_title = src.get(loc.path, max_bytes=8 * 1024 * 1024).title
        except Exception:  # noqa: BLE001 - title is cosmetic
            pass
        self.last_title = c_title
        url = urls.make(src.scheme, loc.rid, loc.path, loc.fragment)
        if not self._guard_done:
            self.guard.arm(url)
        self.setUrl(QUrl(url))

    @property
    def blocked_requests(self):
        return self.blocker.blocked[self._blocked_start:]

    @property
    def served(self):
        return self.handler.served[self._served_start:]

    def closeEvent(self, e):
        if not self._guard_done:
            self.guard.release()          # clean shutdown before any successful load: no crash happened
        self.page().deleteLater()
        super().closeEvent(e)
