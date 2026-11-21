<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# Architecture (task-resources 0.1.0) — implements PHASE4D-PLAN r2 (approved, 8e31648)

```
ui/main_window.py ── library.py (Library: Index + SourcePool) ── index.py (SQLite, FTS5)
      │                     │
      │                     ├─ zim/archive.py   ZimArchive  (python3-libzim: metadata, main page, entries,
      │                     │                    redirects ≤10 with loop detection, SuggestionSearcher, Searcher)
      │                     ├─ docs/epub.py     EpubSource  (zipfile: container → OPF → spine)
      │                     └─ docs/local.py    LocalSource (one HTML/TXT/MD file + its folder, no escape)
      ├─ viewer/light.py   LightViewer (QTextBrowser.loadResource → SourcePool; sanitize.py)
      ├─ viewer/web.py     WebViewer   (QWebEngineUrlSchemeHandler zim:// epub:// local:// → SourcePool;
      │                                 NetworkBlocker interceptor; off-the-record profile)
      ├─ viewer/pdf.py     PdfViewer   (QtPdf, optional)
      └─ discovery.py / importer.py / managed.py / jobs.py (background, cancellable)
```
* URLs: `<scheme>://r<resource id>/<entry path>`; the resource id is our index id, never a file path.
* Every viewer read goes through `Library.source(rid)` → the source adapters. There is no HTTP server, no
  subprocess, no socket in the package (enforced by `tests/test_compat.py`).
* WebEngine: schemes registered before QApplication (`viewer.prepare_before_qapplication`); requests of any other
  scheme are blocked by the interceptor, and `LocalContentCanAccessRemoteUrls=false`; permissions denied;
  no new windows; links are followed by WebEngine and recorded in our own back/forward history.
* Lightweight: HTML sanitised (scripts, handlers, iframes/objects removed; media → placeholder; links rewritten
  to in-app URLs; external links kept visible but never fetched or opened).
* Index: `resource` (reference by real path), `category` + `resource_category` (many-to-many), `meta_override`
  (edits), `bookmark`, `history` (last 500), `titles_fts` (FTS5 on effective values; user text quoted).
* Discovery: unchanged files (path+size+mtime) are not re-read; duplicates found by ZIM UUID or content
  fingerprint (size + sha256 of first/last MiB) are stored linked (`duplicate_of`) and hidden.
* Managed storage: explicit only; `~/.local/share/task-resources/downloads/<category>/` (`/library` protected; fallback
  `~/.local/share/task-resources/managed/<category>/`); `.part` + fsync + `link()` (never overwrites).

## Phase 4E additions (0.2.0)
* `net/safehttp.py` — the only module with network code (enforced by test_compat). stdlib http.client; resolves
  once per hop, refuses non-public addresses, connects to the vetted IP, TLS with SNI + verification, manual
  redirects (max 5, every hop validated, no https→http), size limits, redacted URLs in messages.
* `catalog.py` — OPDS Atom + Metalink parsing (DTD/entities refused), on-disk cache (`~/.cache/task-resources/
  catalog`, 0700, atomic), local search/facets, installed detection by ZIM UUID.
* `downloads.py` — DownloadManager: SQLite queue (`~/.local/share/task-resources/downloads.sqlite`, 0600, WAL),
  one worker thread, states queued/running/paused/waiting/verifying/done/failed/cancelled, crash recovery,
  Range/If-Range resume, `.part` → verify → `os.link` (no overwrite) → index registration in a transaction.
* `ui/downloads_ui.py` — Download tab, Catalog tab, Downloads window; GUI thread only reads SQLite on a timer.
* `managed.py` — usage, `is_managed_path`, `remove_managed` (managed rows inside managed roots only).
* Viewer hardening: the sanitiser strips every non-in-app resource reference (QTextDocument would otherwise load
  `file://` images by itself); Markdown is converted in a detached document and sanitised.
