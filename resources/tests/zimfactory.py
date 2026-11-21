# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Synthetic test archives built with python3-libzim's Creator. No production ZIMs are ever used."""

import struct
import zipfile
import zlib
from pathlib import Path

from libzim.writer import Creator, Hint, Item, StringProvider


def png(w=4, h=3, rgb=(200, 30, 30)):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class _Item(Item):
    def __init__(self, path, title, mimetype, data, front=True):
        super().__init__()
        self.p, self.t, self.m, self.d, self.front = path, title, mimetype, data, front

    def get_path(self):
        return self.p

    def get_title(self):
        return self.t

    def get_mimetype(self):
        return self.m

    def get_contentprovider(self):
        return StringProvider(self.d)

    def get_hints(self):
        return {Hint.FRONT_ARTICLE: self.front, Hint.COMPRESS: True}


HOME = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Field Manual Home</title>
<link rel="stylesheet" href="-/style.css"></head><body>
<h1 id="top">Field Manual</h1>
<p class="note">Water purification basics.</p>
<p><a id="l-boil" href="Boiling_water">Boiling water</a> ·
<a id="l-redirect" href="Purify">Purify (redirect)</a> ·
<a id="l-sub" href="guides/Filters">Filters</a> ·
<a id="l-anchor" href="#table">Jump to table</a> ·
<a id="l-ext" href="https://example.org/outside">External site</a></p>
<img id="logo" src="img/logo.png" alt="logo" onerror="alert(1)">
<img id="extimg" src="EXTERNAL_IMG" alt="external image">
<script>document.title = "SCRIPT-RAN";</script>
<video title="Demo clip" controls><source src="media/clip.webm" type="video/webm"></video>
<table id="table" border="1"><tr><th>Method</th><th>Time</th></tr>
<tr><td>Boil</td><td>1 min</td></tr><tr><td colspan="2">Filter then boil</td></tr></table>
</body></html>"""

BOIL = """<html><head><title>Boiling water</title><link rel="stylesheet" href="-/style.css"></head><body>
<h1>Boiling water</h1><p>Boil water for one minute to purify it. Altitude needs longer.</p>
<p><a id="l-home" href="Home">Back to the manual</a></p></body></html>"""

FILTERS = """<html><head><title>Filters</title></head><body><h1>Filters</h1>
<p>Ceramic filters remove protozoa.</p><img id="sub-img" src="../img/logo.png">
<p><a id="l-up" href="../Boiling_water">Boiling</a></p></body></html>"""

CSS = ".note { color: #ff0000; font-weight: bold; }\nh1 { color: #0000ff; }\n"


def make_zim(path, fulltext=True, title="Field Manual", name="field_manual", external_img="http://127.0.0.1:9/x.png",
             extra_articles=0, language="eng", loop=False):
    path = Path(path)
    c = Creator(str(path))
    if fulltext:
        c.config_indexing(True, "eng")
    with c:
        c.set_mainpath("Home")
        for k, v in {"Title": title, "Description": "Synthetic test archive", "Language": language,
                     "Creator": "T.A.S.K. tests", "Publisher": "T.A.S.K. tests", "Date": "2026-10-13",
                     "Name": name}.items():
            c.add_metadata(k, v)
        c.add_item(_Item("Home", "Field Manual Home", "text/html", HOME.replace("EXTERNAL_IMG", external_img)))
        c.add_item(_Item("Boiling_water", "Boiling water", "text/html", BOIL))
        c.add_item(_Item("guides/Filters", "Filters", "text/html", FILTERS))
        c.add_item(_Item("-/style.css", "", "text/css", CSS, front=False))
        c.add_item(_Item("img/logo.png", "", "image/png", png(), front=False))
        for i in range(extra_articles):
            c.add_item(_Item(f"Article_{i}", f"Article {i}", "text/html",
                             f"<html><head><title>Article {i}</title></head><body><p>Entry {i} text.</p></body></html>"))
        c.add_redirection("Purify", "Purify", "Boiling_water", {Hint.FRONT_ARTICLE: True})
        if loop:
            c.add_redirection("LoopA", "LoopA", "LoopB", {})
            c.add_redirection("LoopB", "LoopB", "LoopA", {})
    return path


def make_epub(path, title="Survival Notes", drm=False):
    path = Path(path)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile '
                   'full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", f'<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
                   'version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                   f'<dc:title>{title}</dc:title><dc:creator>Test Author</dc:creator><dc:language>en</dc:language>'
                   '</metadata><manifest><item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
                   '<item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>'
                   '<item id="i1" href="images/fire.png" media-type="image/png"/></manifest>'
                   '<spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>')
        z.writestr("OEBPS/ch1.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter 1</title>'
                   '</head><body><h1>Fire</h1><img id="fire" src="images/fire.png"/><p><a id="next" '
                   'href="ch2.xhtml">Next chapter</a></p></body></html>')
        z.writestr("OEBPS/ch2.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter 2</title>'
                   '</head><body><h1>Shelter</h1><p>Build above the flood line.</p></body></html>')
        z.writestr("OEBPS/images/fire.png", png(rgb=(255, 120, 0)))
        if drm:
            z.writestr("META-INF/encryption.xml", '<encryption><EncryptedData/></encryption>')
    return path


def make_pdf(path, text="Hello PDF"):
    """Minimal valid one-page PDF (hand-written objects + xref)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    stream = f"BT /F1 18 Tf 20 100 Td ({text}) Tj ET".encode()
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        if o is None:
            out += f"{i} 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream\nendobj\n"
        else:
            out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    Path(path).write_bytes(bytes(out))
    return Path(path)
