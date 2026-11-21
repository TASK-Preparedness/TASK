<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# Known limitations (0.1.0)

Hardware behaviour on the Raspberry Pi is **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**. Everything below was
observed or designed on the development machine with synthetic ZIMs only.

* **Split ZIMs** (`.zimaa`, `.zimab`, …): detected and listed as "split ZIM not supported in this version";
  they are not opened. (libzim can open split archives; wiring and testing it needs a sample — planned.)
* **Cross-ZIM links:** links that point into another ZIM are not followed; only links inside the same archive
  (or EPUB, or the folder of a local HTML file) work.
* **JavaScript:** the lightweight viewer runs **no** JavaScript (scripts are removed; `<noscript>` content is
  shown). Pages that need JS (some zimit/website ZIMs, interactive apps, in-page search boxes) appear static or
  incomplete there. The WebEngine viewer runs page JavaScript, but anything that needs the network fails because
  all non-`zim:`/`epub:`/`local:` requests are blocked; service-worker based ZIMs may not work.
* **Video and audio:** the lightweight viewer shows a labelled placeholder instead of `<video>`/`<audio>`.
  WebEngine playback depends on the codecs in Debian's Qt WebEngine build (H.264/AAC are normally not enabled;
  WebM/VP8/VP9/Opus are more likely) — UNVERIFIED on the Pi.
* **ZIMs without a full-text index:** "Title search only", clearly labelled; no pretend full-text search.
  Search results show titles; libzim's Python binding does not return text snippets.
* **Lightweight viewer CSS:** Qt rich text supports a CSS 2.1 subset: colours, fonts, margins, borders, tables
  (colspan/rowspan). No flexbox/grid, floats, positioning, web fonts, media queries or `:hover`; infoboxes and
  navboxes render as plain tables; inline SVG and MathML are dropped; `srcset` is ignored.
* **Memory on the Pi:** WebEngine starts a Chromium renderer process (typically several hundred MB). libzim
  memory-maps archives (large virtual size, lower resident use). Open files are limited (default 8) and single
  entries above 64 MB are not loaded.
* **PDF** needs python3-pyside6.qtpdf + qtpdfwidgets; without them PDFs are listed but not shown.
  No PDF text search.
* **EPUB:** DRM-encrypted EPUBs are refused; EPUB search covers chapter file names only.
* **ODT/DOCX:** listed with metadata, not displayed.
* Old-namespace ZIMs (before 2021): paths like `A/Foo` are retried without the namespace; untested on real
  old archives.
* No website-to-ZIM conversion (Phase 4F).

## Phase 4E (0.2.0) downloads and catalog
* **Catalog:** the official Kiwix OPDS catalog only (one configurable base URL, `catalog_url`). The whole feed
  (~4.4 MB, ~3.6k entries on 2026-10-13) is downloaded on "Update catalog" and filtered locally. Sizes shown in
  the list are the feed's approximate values; the exact size + sha-256 come from the entry's `.meta4` file at
  download time. Thumbnails are not fetched.
* **Mirrors:** the download uses Kiwix's load-balanced direct URL (it redirects to a mirror, every hop is
  checked). The meta4 mirror list is parsed but automatic mirror fail-over is not implemented.
* **Checksums:** verified when published (Kiwix meta4 sha-256, or a sha256 the user pastes). Plain URL
  downloads without a published checksum are checked for size, type (magic bytes) and, for ZIM, with libzim
  `Archive.check()`; the details say "no published checksum".
* **Verification time:** `Archive.check()` and sha-256 read the whole file; for a 90 GB Wikipedia ZIM this takes
  a long time on a Pi (UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST). The transfer shows "verifying" meanwhile.
* **Network policy:** only http/https on ports 80/443; addresses that resolve to private/loopback/link-local/
  CGNAT/ULA ranges are refused (so a NAS or a LAN web server cannot be used as a source in 0.2.0); no proxy
  support; no authentication/cookies.
* **One transfer at a time** (sequential queue); no bandwidth limiter yet.
* **Website pages:** an HTML page is saved as a single file (no images/CSS crawled); whole-site capture is 4F.
* **Interrupted downloads** resume when the server supports byte ranges with a strong ETag or Last-Modified;
  otherwise they restart from 0 (stated in the transfer note).
* **Offline:** detected when a catalog update fails; transfers that hit a network error wait with backoff
  (30 s → 15 min). There is no OS-level network monitor.

* **Storage (4E audit):** downloads/copies go to `~/.local/share/task-resources/downloads/` only; `/library` is a
  protected root (setting `protected_roots`). Additional storage locations (`extra_storage`) are reserved, not yet used.
