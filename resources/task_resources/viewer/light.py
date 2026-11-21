# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Lightweight viewer: QTextBrowser whose resources (images, stylesheets) come straight from our
libzim / EPUB / local-file layer through loadResource(). No network, no JavaScript.

Limits (Qt rich text): CSS 2.1 subset only (no flex/grid/float layout/positioning, no web fonts), no
JavaScript, no video/audio (placeholder shown), tables supported (colspan/rowspan/borders), SVG images
only when the Qt SVG image plugin is installed."""

from PySide6.QtCore import QByteArray, QRect, Qt, QUrl
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QPen, QTextDocument
from PySide6.QtWidgets import QTextBrowser

from task_resources.viewer import urls
from task_resources.viewer.base import ViewerMixin
from task_resources.viewer.sanitize import sanitise
from task_resources.zim.archive import ZimError


FORMAT_HINT = {"webp": "qt6-image-formats-plugins", "svg": "the Qt SVG image plugin (qt6-svg-plugins)",
               "tiff": "qt6-image-formats-plugins", "tif": "qt6-image-formats-plugins"}
MAX_IMAGE_BYTES = 16 * 1024 * 1024


def supported_formats():
    return {bytes(f).decode().lower() for f in QImageReader.supportedImageFormats()}


def sniff_format(data, path="", mimetype=""):
    """Image format from magic bytes (ZIM paths like 'x.jpg.webp' and wrong MIME types exist)."""
    h = bytes(data[:64])
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP":
        return "webp"
    if h[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if h[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if h[:2] == b"BM":
        return "bmp"
    if h[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    head = bytes(data[:512]).lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head) or "svg" in mimetype:
        return "svg"
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return {"jpg": "jpeg"}.get(ext, ext)


def placeholder(text, width=0, height=0):
    """A small framed box with the image's alt text (shown instead of an image that cannot be displayed)."""
    w = max(120, min(int(width or 0) or 260, 640))
    h = max(28, min(int(height or 0) or 40, 360))
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor("#f4f4f4"))
    p = QPainter(img)
    p.setPen(QPen(QColor("#b0b0b0")))
    p.drawRect(0, 0, w - 1, h - 1)
    p.setPen(QColor("#555555"))
    p.drawText(QRect(6, 2, w - 12, h - 4), int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap), text)
    p.end()
    return img


class LightViewer(ViewerMixin, QTextBrowser):
    name = "lightweight"

    def __init__(self, library, parent=None):
        QTextBrowser.__init__(self, parent)
        self._init_viewer(library)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self._clicked)
        self.report = {}
        self.resource_errors = []
        self.loaded_resources = []
        self.placeholders = []          # (path, reason) — images replaced by an alt-text box
        self.unsupported_formats = set()
        self._img_cache = {}            # url -> QImage (incl. placeholders): no repeated reads / decode failures
        self._formats = supported_formats()

    def _clicked(self, qurl: QUrl):
        s = qurl.toString()
        if s.startswith("#"):
            self._scroll_to(s[1:])
            return
        if urls.parse(s) is None:
            self.blocked.append(s)
            self._emit("blocked", url=s)
            return
        self.open_url(s)

    def _scroll_to(self, frag):
        self.scrollToAnchor(frag)

    def _show_error(self, msg):
        self.setHtml(f"<h3>Cannot show this page</h3><p>{msg}</p>")

    def _render(self, src, loc):
        c = src.get(loc.path)
        self.report = {}
        self.resource_errors = []
        self.loaded_resources = []
        self.placeholders = []
        self.unsupported_formats = set()
        self._img_cache = {}
        mt = c.mimetype.split(";")[0].strip()
        if c.is_html:
            html, self.report = sanitise(c.data, src.scheme, loc.rid, c.path)
            self.blocked.extend(self.report.get("blocked_resources", []))
            self.document().setMetaInformation(QTextDocument.MetaInformation.DocumentUrl,
                                               urls.make(src.scheme, loc.rid, c.path))
            self.setHtml(html)
            self.last_title = self.report.get("title") or c.title
        elif mt == "text/markdown":
            # Markdown → HTML in a detached document (no layout, so nothing is loaded), then the same
            # sanitiser as HTML: ![x](file:///…) or remote images are removed before display.
            tmp = QTextDocument()
            tmp.setMarkdown(c.data.decode("utf-8", "replace"))
            html, self.report = sanitise(tmp.toHtml(), src.scheme, loc.rid, c.path)
            self.blocked.extend(self.report.get("blocked_resources", []))
            self.setHtml(html)
            self.last_title = c.title
        elif mt.startswith("text/"):
            self.setPlainText(c.data.decode("utf-8", "replace"))
            self.last_title = c.title
        elif mt.startswith("image/"):
            self.setHtml(f'<img src="{urls.make(src.scheme, loc.rid, c.path)}"/>')
            self.last_title = c.title
        else:
            self.setHtml(f"<p>{c.path}: {mt} cannot be shown in the lightweight viewer.</p>")
            self.last_title = c.title
        if loc.fragment:
            self.scrollToAnchor(loc.fragment)

    def loadResource(self, rtype, qurl):
        p = urls.parse(qurl.toString())
        if p is None:
            if qurl.scheme() in ("http", "https", "ftp", "file", "ws", "wss"):
                self.blocked.append(qurl.toString())
            return None
        _, rid, path, _ = p
        image = rtype == QTextDocument.ResourceType.ImageResource
        key = qurl.toString()
        if image and key in self._img_cache:
            return self._img_cache[key]
        try:
            c = self.library.source(rid).get(path)
        except (ZimError, OSError) as exc:
            self.resource_errors.append((path, str(exc)))
            if image:
                return self._placeholder(key, path, "not in this file")
            return None
        self.loaded_resources.append(c.path)
        if image:
            return self._image(key, path, c)
        if rtype == QTextDocument.ResourceType.StyleSheetResource:
            from task_resources.viewer.sanitize import clean_css, resolve_rel
            css, gone = clean_css(c.data.decode("utf-8", "replace"),
                                  lambda v: resolve_rel(p[0], rid, c.path, v))
            self.blocked.extend(gone)
            return css
        return c.data

    def _image(self, key, path, c):
        fmt = sniff_format(c.data, c.path, c.mimetype)
        if len(c.data) > MAX_IMAGE_BYTES:
            return self._placeholder(key, path, "image too large for the lightweight reader")
        if fmt and fmt not in self._formats:
            self.unsupported_formats.add(fmt)
            return self._placeholder(key, path, f"{fmt.upper()} image — not supported by this system's Qt"
                                     + (f" (needs {FORMAT_HINT[fmt]})" if fmt in FORMAT_HINT else ""))
        img = QImage()
        if not img.loadFromData(QByteArray(bytes(c.data)), fmt.upper() if fmt in self._formats else None):
            img = QImage.fromData(bytes(c.data))
        if img.isNull():
            self.resource_errors.append((path, "image could not be decoded"))
            return self._placeholder(key, path, "image could not be decoded")
        limit = max(200, self.viewport().width() - 40)
        if img.width() > limit:                 # wide figures: fit the reading width (aspect kept)
            img = img.scaledToWidth(limit, Qt.TransformationMode.SmoothTransformation)
        self._img_cache[key] = img
        return img

    def _placeholder(self, key, path, reason):
        alt = (self.report.get("img_alt") or {}).get(key, "")
        self.placeholders.append((path, reason))
        img = placeholder(f"[image: {alt}] — {reason}" if alt else f"[image] — {reason}")
        self._img_cache[key] = img
        return img
