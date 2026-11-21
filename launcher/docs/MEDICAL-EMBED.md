# Phase 4F.3 — Medical embeds T.A.S.K. Resources (launcher 0.3.5, task-resources 0.2.2)

## What the user gets
Tapping the Medical tile opens the Medical view **inside the launcher window**. The view is T.A.S.K. Resources' own browser and reader, running in the launcher process. It offers:
* categories, a resource list and metadata (with "Listed because …");
* metadata search (the FTS title index) and "Search inside ZIMs": article full-text (Xapian) where the ZIM has an index, title search otherwise, run in a background thread;
* the embedded ZIM reader: WebEngine if installed and registered at launcher start, else the lightweight QTextBrowser reader;
* Back, Forward, Main page and search-inside;
* bookmarks, plus the launcher's own Back/Home/Refresh.

The list is filtered to medical by default; "Everything in the library (unfiltered)" is one click away. Only indexed resources are listed. Nothing opens an external window or browser for normal reading.

## Shared component (smallest refactor)
`task_resources/ui/browser.py` holds the code moved out of `MainWindow` (list, details, reader page) as:
* `ResourceBrowser` and `ReaderPane` (QWidgets);
* `Scope`, a filter;
* `IndexBookmarks` (standalone) and `JsonBookmarks` (embedders).

`MainWindow` composes it and keeps Add/Rescan/Downloads/Edit/Forget/Delete. Old attribute names still work through delegation, so the existing tests are unchanged.

## Read-only open
`Index(path, read_only=True)` / `Library(..., read_only=True)` work as follows:
* The file must already exist.
* It is opened with `file:…?mode=ro` plus `PRAGMA query_only=ON`.
* No mkdir, chmod, DDL, WAL pragma or meta insert.
* Writes raise `ReadOnlyIndex`; history is skipped.
* A newer schema or a corrupt file is refused with a message.

SQLite may create an empty `-wal` and a `-shm` lock map next to a WAL database for any reader. They contain no data. The tests assert that `index.sqlite` and every ZIM are byte-identical and that `-wal` is empty.

## Medical classification (`task_resources/classify.py`)
The first matching rule wins:
1. explicit category "Medical";
2. named collections: MDWiki, WikEM, MedlinePlus, Medicine LibreTexts, Military Medicine, Medical Library, Hesperian, Where There Is No Doctor;
3. conservative keywords (medicine/medical, first aid, health, anatomy, pharmacology, nursing, emergency care, clinical/surgery/disease/dental).

Rules run on indexed metadata only: title, name, description, publisher, creator, file name and categories. The index stores no ZIM "Tags", so tags are not used.

## Lock, instances, errors
* **Lock:** the view clears the reader, details and hits, and returns to Home under the overlay.
* **Instances:** there is one view and one browser per launcher, with one viewer per engine (reused).
* **Errors:** a missing file gives "File missing …"; a damaged ZIM gives "This ZIM could not be read … not modified". A missing index, an old or missing task-resources, or missing libzim each give a message, with no fallback to an external app.

## Not done / limits
* WebEngine in the launcher only works when its schemes are registered before QApplication; `task_launcher.app` does this when task-resources is importable. Otherwise the lightweight reader is used (JS/CSS-light).
* QtWebEngine is optional (~190 MB). The embedded reader has been tested with the lightweight engine only; WebEngine embedding in the launcher is UNVERIFIED on the Pi.
* Bookmarks made in Medical live in `~/.local/state/task-launcher/medical-bookmarks.json`, separate from Resources' own bookmarks. This is by design, to keep the index read-only.
