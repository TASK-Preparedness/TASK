<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# Phase 4E specification — downloads and online ZIM catalog (IMPLEMENTED in task-resources 0.2.0)

Status: implemented in 0.2.0 (branch phase4e). Differences from this spec, decided while implementing:
* Catalog base is `https://opds.library.kiwix.org/catalog/v2` (library.kiwix.org answers 301 there); the full feed
  is fetched with `count=-1` (documented in kiwix-tools' server docs) and cached; filtering is local.
* Acquisition links are Metalink 4 (`.zim.meta4`) files, which give the exact size + sha-256; the feed `length`
  is approximate. A `.sha256` sidecar also exists on download.kiwix.org but the meta4 is used.
* Redirect limit 5; concurrency 1; no bandwidth limit yet (see LIMITATIONS.md).
* Failed verification keeps the data as `.<name>.part-failed` (hidden), never registered.

## Tab B — Download from Website
Paste a website page or a direct document URL; choose category and format; download into managed storage
(`~/.local/share/task-resources/downloads/<category>/`; 4E audit: never /library); show progress, failures and free space.
An incomplete download is never shown as a resource.

## Tab C — Online ZIM Catalog
Search Kiwix-compatible OPDS catalogs (default `https://library.kiwix.org/catalog/v2/entries`, configurable),
show title/description/language/size/date, download the chosen ZIM into the managed library, verify it, then
register it with the native engine (no Kiwix involvement).

## Job engine (extends `task_resources/jobs.py`)
* Persistent state in `jobs.sqlite` (0600): id, kind, url, final URL, dest, state
  (queued|running|paused|verifying|done|failed|cancelled), bytes done/total, ETag/Last-Modified, expected size
  and checksum, error, timestamps. On start, `running` → `paused` (recover after crash/power loss).
* Download to `<dest>.part` in the destination folder; resume with `Range` + `If-Range` (ETag/Last-Modified);
  server ignoring ranges → restart from 0; size limit; fsync; verify; `link()`/`rename` atomically; index only after
  verification succeeded.
* Integrity: sha256 from the catalog (`.sha256` / Metalink `meta4` hashes where offered) or trusted metadata;
  for ZIM also `libzim Archive.check()` (internal MD5). Mismatch → file kept as `.part-failed`, never registered.
* Disk space: refuse when free − expected < reserve (default 1 GiB, setting); re-check every 64 MiB.
* Concurrency 1 (setting up to 2), bandwidth limit, pause/resume/cancel, no autostart, no root.
* **SSRF-safe networking:** only `http`/`https`; default ports 80/443; resolve the host and reject loopback,
  RFC 1918, CGNAT 100.64/10, link-local, ULA fc00::/7, multicast, unspecified and IPv4-mapped private addresses;
  connect to the vetted IP with SNI/Host of the name (no re-resolution → DNS-rebinding safe); validate **every**
  redirect hop the same way (max 5); no credentials in URLs; no cookies; response-type checks; logs without query
  strings. Tests: table of addresses, redirect to 127.0.0.1/10.x/169.254.x/[::1], rebinding, oversize, truncated
  transfer, power-cut resume, checksum mismatch, full disk.
* Offline behaviour: tabs show "offline" without trying; nothing blocks the UI.
