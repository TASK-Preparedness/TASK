<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# T.A.S.K. Resources — user guide

## Opening
From the launcher **Library** tile (launcher 0.3.1 opens T.A.S.K. Resources when it is installed), the
application menu, or `task-resources`. On start it scans the configured folders in the background
(`--no-scan` skips this). The status bar shows progress; scanning never writes to the scanned folders.

## The window
* **Left:** categories — *All resources*, *Uncategorised* and your own categories with counts.
* **Middle:** resources. "— file missing" means the file was not found at its path; the entry, its categories,
  edits and bookmarks are kept until you choose **Forget**.
* **Right:** details (title, file, size, language, categories, search capability, other copies) with
  **Open**, **Edit…** and **Forget** (Forget removes the index entry only; the file stays).

## Finding things
* **Find a resource** (top field): searches titles, descriptions, creators, publishers, languages, categories,
  file names and notes in the T.A.S.K. index. It does not look inside files.
* **Search inside** (reader bar): for a ZIM with a full-text index, libzim full-text search
  ("Full-text results: N"); for a ZIM without one, title matches only, labelled
  **"Title search only — this ZIM has no full-text index"**. EPUB: chapter file names only.

## Reading
**◀ Back / Forward ▶ / Main page / ☆ Bookmark / Close.** Links inside the same ZIM or EPUB open in the reader.
Links to other websites are **not opened** (the status bar shows the address). PDFs open in the PDF view
(page scrolling, fit to width) if QtPdf is installed.

## Viewer setting
The combo box at the top: **automatic** (WebEngine if installed, else lightweight), **WebEngine**,
**lightweight**. The choice is saved in `~/.config/task-resources/settings.json`. If WebEngine is chosen but not
installed, the lightweight viewer is used and a note says so. Use the lightweight viewer on a low-memory Pi.

## Adding resources (Add Resource)
* **Import from Pi:** add files or folders; choose a category and optionally a title/description. By default
  files are **registered in place**. Tick **Copy into managed storage** only if you want a copy:
  it goes to `~/.local/share/task-resources/downloads/<category>/` (never into `/library`). Copies never overwrite, check free
  space first and are finished atomically (no half files). Duplicates are refused unless
  **Add even if it is a duplicate** is ticked.
* **Download from Website / Online ZIM Catalog:** visible but disabled — *Available in Phase 4E*.

## Editing
**Edit…** changes title, description, language, creator, publisher, date, notes and categories (comma separated).
Edits are stored in the T.A.S.K. index only; clearing a field back to the original value removes the edit.

## Settings file (`~/.config/task-resources/settings.json`, 0600)
`scan_dirs`, `library_xml`, `kiwix_desktop_dir`, `managed_root`, `free_space_reserve_mb`, `viewer`,
`open_archive_cache` (open files kept, default 8), `max_item_mb` (largest page/image loaded, default 64).

## Downloads (0.2.0)
Nothing is contacted until you ask. Downloads need an Internet connection; everything else works offline.

**Online ZIM Catalog** (Add Resource → Online ZIM Catalog): press *Update catalog* once; the list is saved and
stays browsable offline (the header shows its date, and "offline" when the update failed). Search titles and
descriptions; filter by category, language, subject and maximum size. *Installed* = already in your library
(same ZIM UUID). Choose a destination (default: T.A.S.K. managed storage) and press *Download and verify*.

**Download from Website**: paste an address of a ZIM, PDF, EPUB, HTML, TXT or Markdown file. *Check address*
shows the file name, size and whether the server can resume. Pick a category (and more in "Also in"), a
destination and optionally a published SHA-256, then *Add to downloads*.

**Downloads window** (toolbar *Downloads*): tabs Active, Queued, Paused, Completed, Failed with progress,
bytes, speed, ETA and notes; buttons Pause, Resume, Cancel (asks; deletes the partial data), Retry and Remove
from list. Closing the program pauses a running transfer; it can be resumed later, also after a power cut.

A download appears in the library only after it was checked (size, checksum when published, file type, and
for ZIMs the libzim integrity check). Files in managed storage (`~/.local/share/task-resources/downloads/<category>/`; `/library` is never
written — downloads into it are refused, existing ZIMs there are only read)
can be deleted with *Delete file…* (asks first). Files elsewhere — your existing ZIM library — are protected:
*Forget* only removes them from the list.
