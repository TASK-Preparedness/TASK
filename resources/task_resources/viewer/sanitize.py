# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Make archive HTML safe and usable for the lightweight (QTextBrowser) viewer.

* removes <script>, <iframe>, <object>, <embed>, <form> controls, inline event handlers, javascript: URLs;
* <video>/<audio> become a labelled placeholder (the lightweight viewer cannot play media);
* relative href/src are resolved against the entry path and rewritten to in-app URLs;
* external links stay visible but are marked and are never fetched or opened;
* any resource reference (img/src, stylesheet href, poster, CSS url()) that is not an in-app URL or a
  data:image is REMOVED before Qt sees it. QTextDocument resolves file:// images on its own, bypassing
  loadResource(); removing them here is what keeps file:// and local interfaces unreachable (4E fix);
* <noscript> content is kept (it is what a reader without JavaScript should see);
* inline <svg> and srcset are dropped (unsupported by Qt rich text).
Uses only html.parser (stdlib).
"""

import html
import re
from html.parser import HTMLParser

from urllib.parse import unquote

from task_resources.viewer import urls
from task_resources.zim.archive import join

DROP_WITH_CONTENT = {"script", "iframe", "object", "embed", "svg", "math", "template", "canvas", "select",
                     "textarea", "button"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
        "track", "wbr"}
MEDIA = {"video", "audio"}
URL_ATTRS = {"href", "src", "poster"}
DROP_ATTRS = {"srcset", "sizes", "integrity", "crossorigin", "ping", "formaction", "action"}


_CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I | re.S)
_CSS_IMPORT = re.compile(r"@import\s+(['\"])(.*?)\1", re.I)


def _internal(v):
    low = v.strip().lower()
    return low.startswith(tuple(f"{x}://" for x in urls.SCHEMES)) or low.startswith("data:image/")


def clean_css(css, resolve=None):
    """Drop every url()/@import target that is not in-app (after optional resolve of relative ones)."""
    removed = []

    def sub(m):
        target = m.group(2).strip()
        if resolve and not urls.is_external(target) and not target.lower().startswith("data:"):
            target = resolve(target)
        if _internal(target):
            return f'url("{target}")'
        removed.append(target)
        return "url()"

    css = _CSS_IMPORT.sub(lambda m: "" if not _internal(m.group(2)) else m.group(0), css)
    return _CSS_URL.sub(sub, css), removed


def resolve_rel(scheme, rid, base, v):
    """Relative reference -> in-app URL. 0.2.4: the reference is percent-decoded BEFORE joining (HTML hrefs are
    URL-encoded, ZIM entry paths are not; urls.make() encodes again). Previously "../I/A_%28b%29.jpg" became
    the entry path "I/A_%28b%29.jpg" and was not found."""
    path, _, frag = v.partition("#")
    path = path.split("?", 1)[0]
    return urls.make(scheme, rid, join(base, unquote(path)), unquote(frag))


TABLE_DEFAULTS = (("border", "1"), ("cellspacing", "0"), ("cellpadding", "4"))


def _table_attrs(clean):
    """Qt rich text ignores most article CSS for tables; give it the HTML attributes it does honour."""
    d = {k for k, _ in clean}
    cls = dict(clean).get("class", "").lower()
    out = list(clean) + [(k, v) for k, v in TABLE_DEFAULTS if k not in d]
    if any(c in cls for c in ("infobox", "sidebar", "navbox-vertical")) and "align" not in d:
        out += [("align", "right"), ("width", "38%")]
    elif "width" not in d and "wikitable" in cls:
        out.append(("width", "100%"))
    return out


class _Sanitiser(HTMLParser):
    def __init__(self, scheme, rid, base_path):
        super().__init__(convert_charrefs=True)
        self.scheme, self.rid, self.base = scheme, rid, base_path
        self.out = []
        self.skip = 0              # depth inside dropped elements
        self.media = 0
        self.title = ""
        self._in_title = False
        self.external_links = 0
        self.removed_scripts = 0
        self.media_placeholders = 0
        self.stylesheets = []
        self.blocked_resources = []
        self.img_alt = {}          # in-app image URL -> alt text (placeholders in the lightweight viewer)
        self._in_style = False

    def _url(self, value, tag, attr):
        v = value.strip()
        low = v.lower()
        if low.startswith(("javascript:", "vbscript:")):
            return None
        if low.startswith("data:"):
            return v if (tag == "img" and len(v) < 512 * 1024 and low.startswith("data:image/")) else None
        if v.startswith("#"):
            return v
        if urls.is_external(v):
            return v       # kept as text/link target; the viewer never fetches or opens it
        return self._resolve(v)

    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs, closed=False)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs, closed=True)

    def _start(self, tag, attrs, closed):
        if tag == "title":
            self._in_title = True
        if tag == "style" and not closed:
            self._in_style = True
        if self.skip:
            if tag in DROP_WITH_CONTENT and not closed and tag not in VOID:
                self.skip += 1
            return
        if tag in DROP_WITH_CONTENT:
            if tag == "script":
                self.removed_scripts += 1
            if not closed and tag not in VOID:
                self.skip = 1
            return
        if tag in MEDIA:
            self.media_placeholders += 1
            label = dict(attrs).get("title") or dict(attrs).get("aria-label") or tag
            self.out.append(f'<p class="task-media"><i>[{html.escape(tag)}: {html.escape(label)} — '
                            'not playable in the lightweight viewer]</i></p>')
            if not closed:
                self.media += 1
            return
        if self.media and tag in ("source", "track"):
            return
        if tag == "noscript":
            return        # keep children, drop the wrapper
        if tag in ("base", "meta"):
            return
        clean = []
        external = False
        for k, v in attrs:
            k = k.lower()
            if v is None:
                v = ""
            if k.startswith("on") or k in DROP_ATTRS or k == "style" and "expression(" in v.lower():
                continue
            if k in URL_ATTRS:
                nv = self._url(v, tag, k)
                if nv is None:
                    continue
                if tag == "a" and urls.is_external(nv):
                    external = True
                elif tag != "a" and not _internal(nv) and not nv.startswith("#"):
                    self.blocked_resources.append(nv)      # never handed to Qt
                    continue
                v = nv
            if k == "style" and "url(" in v.lower():
                v, gone = clean_css(v, self._resolve)
                self.blocked_resources += gone
            clean.append((k, v))
        if tag == "link":
            d = dict(clean)
            if "stylesheet" in d.get("rel", "").lower() and d.get("href"):
                self.stylesheets.append(d["href"])
                self.out.append(f'<link rel="stylesheet" type="text/css" href="{html.escape(d["href"])}"/>')
            return
        if tag == "img":
            d = dict(clean)
            if d.get("src", "").startswith(tuple(f"{x}://" for x in urls.SCHEMES)):
                self.img_alt[d["src"]] = d.get("alt", "")
        if tag == "table":
            clean = _table_attrs(clean)
        if tag == "a" and external:
            self.external_links += 1
            clean.append(("title", "external link — not opened (offline reader)"))
            clean.append(("class", "task-external"))
        a = "".join(f' {k}="{html.escape(v, quote=True)}"' for k, v in clean)
        self.out.append(f"<{tag}{a}{'/' if closed or tag in VOID else ''}>")

    def _resolve(self, v):
        return resolve_rel(self.scheme, self.rid, self.base, v)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "style":
            self._in_style = False
        if self.skip:
            if tag in DROP_WITH_CONTENT:
                self.skip -= 1
            return
        if tag in MEDIA:
            self.media = max(0, self.media - 1)
            return
        if tag in VOID or tag in ("noscript", "base", "meta", "link") or tag in DROP_WITH_CONTENT:
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self.skip or self.media:
            return
        if self._in_style:
            data, gone = clean_css(data, self._resolve)
            self.blocked_resources += gone
        self.out.append(html.escape(data, quote=False))


EXTRA_CSS = ("a.task-external { color: #8a6d00; } p.task-media { color: #555; } "
             "a { color: #0645ad; } "
             "h1 { font-size: x-large; margin-top: 4px; margin-bottom: 6px; } "
             "h2 { font-size: large; margin-top: 16px; margin-bottom: 4px; } "
             "h3 { font-size: medium; margin-top: 12px; margin-bottom: 2px; } "
             "p { margin-top: 4px; margin-bottom: 6px; } "
             "table { border-collapse: collapse; margin-top: 6px; margin-bottom: 8px; } "
             "td, th { border: 1px solid #a2a9b1; padding: 4px; vertical-align: top; } "
             "th { background-color: #eaecf0; font-weight: bold; } caption { font-weight: bold; } "
             "table.infobox { background-color: #f8f9fa; margin-left: 12px; } "
             "pre, code { background-color: #f6f6f6; font-family: monospace; } "
             "blockquote { margin-left: 16px; color: #333; } "
             "img { max-width: 100%; }")


def sanitise(data, scheme, rid, base_path):
    """-> (html, report dict)."""
    text = data.decode("utf-8", "replace") if isinstance(data, (bytes, bytearray)) else str(data)
    p = _Sanitiser(scheme, rid, base_path)
    p.feed(text)
    p.close()
    body = "".join(p.out)
    report = {"title": " ".join(p.title.split()), "scripts_removed": p.removed_scripts,
              "external_links": p.external_links, "media_placeholders": p.media_placeholders,
              "stylesheets": p.stylesheets, "blocked_resources": p.blocked_resources, "img_alt": p.img_alt}
    return f"<style>{EXTRA_CSS}</style>" + body, report
