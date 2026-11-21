<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# task-maps architecture

## Modules

| Module | Role |
|---|---|
| `tilemath` | Web Mercator math: lat clamp ±85.0511287798066°, lon wrap, tile ↔ lon/lat, XYZ↔TMS flip, `BBox` (west > east = crosses the antimeridian, split into two column ranges), deterministic tile iteration with an arithmetic resume cursor, scale bar, haversine, coordinate formats/parsing. |
| `mbtiles` | MBTiles 1.3 create/read/check, tile validation (PNG/JPEG/WebP magic + trailer, 67 B–4 MiB), `TileWriter` (the only writer of a file). |
| `sources` | Source TOML schema 1, download policy, API keys. |
| `jobs` | Persistent download jobs (`jobs.sqlite`, WAL): state, cursor, counters, failed tiles. |
| `net` | urllib fetch with identifying User-Agent, Retry-After parsing, redirect scheme check. |
| `downloader` | `DownloadEngine` (producer + ≤4 workers, rate limiter, backoff, holds, checkpoints) and `JobManager` (one engine at a time, one writer per map file, capacity checks). |
| `gpsd` | gpsd JSON client (thread), `GpsState`. |
| `core` | One read-only rain-core v2 `capability.list` request. |
| `waypoints`, `gpx` | SQLite store, track filter, GPX 1.1 export/parse. |
| `layers` | Map file discovery, offline import. |
| `ui/*` | `MapView` (renderer), `TileLoader` (decode threads), panels, `MainWindow`. |

## Renderer decision: own QWidget renderer (QtLocation rejected)

Checked 2026-10-10: Debian trixie ships `python3-pyside6.qtlocation` 6.8.2.1, but in Qt 6 the map
display (`MapView`/`Map` item) exists **only as a QML type** — there is no QWidget map — and its
tile plugins (osm, …) are online tile fetchers with a disk cache; there is no MBTiles plugin.
Using it would mean a QML scene, writing a custom geoservices plugin in C++ for MBTiles, and
fighting the plugin's own online fetching (which by default targets OSM-run servers). Our own
renderer is ~700 lines of QPainter, reads MBTiles directly, and makes every state (overzoom,
missing, pending, failed) explicit.

Rendering: the display zoom is fractional; tiles come from level `L = clamp(round(zoom),
minzoom..maxzoom)` and are drawn scaled by `2^(zoom−L)`. Tiles are requested centre-first;
`TileLoader` decodes PNG/JPEG/WebP into `QImage` on two worker threads (one read-only SQLite
connection each), LIFO with a 4000-request cap and generations so stale requests are dropped.
The decoded cache is an LRU bounded by count (Settings, default 512), plus a bounded set of
known-absent tiles (50 000). The GUI thread never touches SQLite for tiles.

**Overzoom** (zoom > file max zoom + 0.5): the deepest tile is scaled up, drawn with an amber
dashed edge ("overzoom from zN" on large tiles) and the status bar shows "Overzoom ×k (map data
ends at zN)". A tile **missing** at a level the file covers is hatched "No offline coverage"; if a
lower-zoom ancestor exists it is shown dimmed under the hatch with "(zN shown)". While a running
download covers a missing tile it is drawn as **downloading…** (blue dashed); tiles that failed
are red-crossed **failed**. When the writer commits tiles, `on_tiles` → `MapView.tiles_committed`
invalidates exactly those cache entries (live refresh).

## Storage decision

* One MBTiles file per source (`maps/<source>.mbtiles`); a downloaded *region* is a job row.
  Overlapping regions therefore share tiles, duplicates are skipped (`INSERT OR IGNORE`, the
  existing tile is kept) and the producer skips tiles already present without a request.
* MBTiles 1.3: `metadata(name,value)`, `tiles(zoom_level,tile_column,tile_row,tile_data)` with a
  unique index; rows are TMS (`row = 2^z − 1 − y`). Metadata: name, format (from the first tile),
  bounds/center/minzoom/maxzoom (union of the source's jobs), attribution, type, version.
* WAL, `synchronous=NORMAL`. `TileWriter` is the only writer: it batches 64 tiles or 0.5 s per
  `BEGIN IMMEDIATE … COMMIT` and runs `wal_checkpoint(PASSIVE)` every 20 commits.
* Disk full (`SQLITE_FULL` / "database or disk is full"): the batch is rolled back, the writer
  enters a *full* state and refuses writes, the job goes to **paused-disk** and the affected tiles
  are queued again; nothing partial is committed. A capacity check every 100 tiles pauses the job
  before the free space drops under the reserve (default 200 MB). Resume after freeing space.
* Imports go through `PRAGMA integrity_check` and are copied with the SQLite backup API (a
  consistent copy even with a `-wal` file) to `.part` then renamed, or symlinked.
* Upgrades never delete or migrate maps: the package owns no user data.

## Download engine

Producer iterates tiles from the job cursor, skips present tiles, queues the rest (bounded queue).
Workers take a global rate-limiter slot (`1/rate_limit` spacing across all workers), fetch, then:
200 → validate (twice corrupt → failed) → writer; 204/404 → failed ("not available"); 429/503 →
global hold for `Retry-After` (seconds or HTTP date, max 900 s) or jittered backoff; 401/403 →
failed, 5 in a row pause the job; other statuses → exponential backoff with jitter (base 1 s, cap
60 s, 5 attempts). Network errors: 3 consecutive → **waiting-network** with a growing hold (≤60 s);
the first successful response resumes automatically. The cursor only advances over contiguous
finished tiles (out-of-order completions are remembered), and is checkpointed every second, so a
crash re-fetches at most the in-flight window. On start, jobs left `running` become
`interrupted` and the UI offers to resume. Identical active jobs are refused (duplicate-job
protection); only one engine runs at a time.

## GPS source decision

rain-core 0.2.1 has no position method: `gps.position` exists only as a capability in
`capability.list` (Phase 1 registers no providers). So positions come from **gpsd** (JSON on
127.0.0.1:2947, the client only sends `?WATCH={"enable":true,"json":true}`; the serial device is
never opened by task-maps). The GPS panel also shows Core's `gps.position` status (one read-only
public request). When Core gains a position provider, `core.py` is the place to add it.

## Threads

GUI thread; `TileLoader` ×2; download producer + workers; `TileWriter` per map file; gpsd client;
short-lived threads for estimates, imports and the Core probe. Background callbacks reach the GUI
through a `Bridge` QObject (queued signals); callbacks after shutdown are ignored.
