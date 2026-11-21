# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Offline medical REFERENCE discovery (no patient records, no clinical decision support).

Sources: Kiwix collections whose name/title/tags/category match medical keywords (from the Library
discovery), IIAB/RACHEL-style content modules under /library/www/html/modules, and folders listed
in reference.toml [medical] dirs (PDF/HTML/EPUB files). Matching is by keywords only and says
nothing about the quality or currency of the content.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

MEDICAL_RE = re.compile(r"(medic|mdwiki|wikem|medline|health|first[ _-]?aid|anatomy|pharma|nursing|"
                        r"hesperian|wikimed|disease|clinic|surg|emergency|who[_-]|cdc|msf|dental)", re.I)
MODULE_DIRS = (Path("/library/www/html/modules"),)
DOC_EXT = {".pdf", ".html", ".htm", ".epub", ".txt"}
DISCLAIMER = ("Reference material only. Matched by title/tag keywords; not reviewed, not a clinical "
              "decision tool. No patient data is stored.")


@dataclass
class MedicalStatus:
    books: list = field(default_factory=list)       # kiwix.Book
    modules: list = field(default_factory=list)     # (name, path to index.html or dir)
    documents: list = field(default_factory=list)   # (folder, [paths])
    missing_dirs: list = field(default_factory=list)
    kiwix_ready: bool = False

    @property
    def count(self):
        return len(self.books) + len(self.modules) + sum(len(d[1]) for d in self.documents)

    def summary(self):
        if not self.count:
            return "No offline medical reference found"
        parts = []
        if self.books:
            parts.append(f"{len(self.books)} Kiwix")
        if self.modules:
            parts.append(f"{len(self.modules)} IIAB module{'s' if len(self.modules) != 1 else ''}")
        docs = sum(len(d[1]) for d in self.documents)
        if docs:
            parts.append(f"{docs} document{'s' if docs != 1 else ''}")
        return "Reference: " + " · ".join(parts)


def is_medical(book) -> bool:
    text = " ".join([book.name, book.title, book.tags, book.category])
    return bool(MEDICAL_RE.search(text))


def collect(kiwix_status=None, ref_dirs=(), module_dirs=MODULE_DIRS, max_docs=500):
    st = MedicalStatus()
    if kiwix_status is not None:
        st.kiwix_ready = kiwix_status.ready
        st.books = [b for b in kiwix_status.books if is_medical(b)]
    for md in module_dirs:
        try:
            names = sorted(os.listdir(md))
        except OSError:
            continue
        for n in names:
            if MEDICAL_RE.search(n) and (md / n).is_dir():
                idx = md / n / "index.html"
                st.modules.append((n, str(idx if idx.is_file() else md / n)))
    for d in ref_dirs:
        p = Path(d)
        if not p.is_dir():
            st.missing_dirs.append(d)
            continue
        found = []
        for root, dirs, files in os.walk(p):
            depth = len(Path(root).relative_to(p).parts)
            if depth >= 2:
                dirs[:] = []
            for f in sorted(files):
                if os.path.splitext(f)[1].lower() in DOC_EXT:
                    found.append(os.path.join(root, f))
                    if len(found) >= max_docs:
                        break
            if len(found) >= max_docs:
                break
        st.documents.append((d, found))
    return st
