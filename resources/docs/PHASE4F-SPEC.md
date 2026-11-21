<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# Phase 4F specification — creating ZIMs from websites (research/spec only)

Not a tab in the Add Resource dialog; a separate future feature. Nothing here is implemented.

## Candidate tools (openZIM project; none is packaged in Debian trixie — checked 2026-10-13 against the trixie
arm64 package index: no `zimit`, `warc2zim` or `mwoffliner` packages)
* **zimit** — crawls a site with the Browsertrix crawler (headless Chromium) into WARC, then converts with
  warc2zim. Distributed upstream mainly as a container image. arm64 image availability and resource use on a Pi:
  UNVERIFIED.
* **warc2zim** — Python tool converting existing WARC files to ZIM (useful when the crawl is done elsewhere).
* **mwoffliner** — Node.js scraper for MediaWiki sites only (uses the MediaWiki API).
* zim-tools (`zimcheck`, in trixie 3.5.0) for validating results.
Versions, licences and exact CLI options must be re-verified from upstream when 4F starts.

## Requirements
* Runs as the desktop user (rootless container or venv), never as root, no system service, no autostart.
* User-entered seed URL and an enforced **scope** (same domain / URL prefix), page limit (e.g. 2 000), size
  limit (e.g. 2 GiB), time limit (e.g. 2 h), CPU/RAM limits (`systemd-run --user --scope -p MemoryMax=…
  -p CPUQuota=…` or container limits).
* Network rules from 4E apply to the seed and to the crawler: no private, loopback, link-local or CGNAT targets;
  robots.txt honoured; polite rate.
* Output to managed storage via `.part` + atomic finalize, checked with zimcheck/libzim, then indexed by the native
  engine. The user is shown the source site's licence/attribution responsibility.
* Practical recommendation: crawl on a more powerful machine and import the ZIM via "Import from Pi".
