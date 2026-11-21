<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# T.A.S.K. Resources 0.2.0 (Phase 4D + 4E downloads)

Native offline library and reader for the T.A.S.K. platform, built on **python3-libzim** and PySide6.
It is its own ZIM reader: it does **not** use Kiwix, kiwix-serve, any HTTP server or a web browser, and it
never starts, stops or reconfigures Kiwix/IIAB services. Kiwix can stay installed independently.

* Finds resources **in place, read-only**: `/library/zims/content`, `/library/working/zims`,
  `/library/zims/library.xml`, `~/.local/share/kiwix-desktop/*.xml` (all configurable) and files you add.
  Nothing in those locations is moved, copied, renamed, chmod/chowned or written.
* Formats: ZIM (libzim), PDF (QtPdf, optional), EPUB (zipfile adapter), TXT, Markdown, HTML.
  ODT/DOCX are listed with metadata but not shown.
* Private index (`~/.local/share/task-resources/index.sqlite`, 0600): categories (many-to-many), edited metadata
  (stored separately, the file is never changed), duplicates (ZIM UUID / content fingerprint / same real path),
  missing-file marking, bookmarks, history.
* Two different searches: **Find a resource** (titles and metadata in our index) and **Search inside**
  (libzim full-text search when the ZIM has an Xapian index; otherwise clearly "Title search only").
* Two viewers, chosen in the window (setting `viewer`: auto / webengine / lightweight), automatic fallback:
  Qt WebEngine (optional) via a `zim://` scheme handler, or a lightweight QTextBrowser viewer.
  Both read only through our libzim/EPUB/local-file layer. External network requests are blocked.
* Add Resource: **Import from Pi** works; **Download from Website** and **Online ZIM Catalog** are present but
  disabled ("Available in Phase 4E").

Run: `task-resources [--viewer auto|webengine|lightweight] [--no-scan]`. Refuses to run as root.
Docs: `docs/USER-GUIDE.md`, `docs/LIMITATIONS.md`, `docs/ARCHITECTURE.md`, `docs/PHASE4E-SPEC.md`,
`docs/PHASE4F-SPEC.md`. Licence GPL-3.0-or-later.
