<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# Tile sources and the offline-download policy

task-maps downloads map tiles **only** from sources whose terms permit offline/bulk use, at a
conservative rate, with an identifying User-Agent
(`task-maps/0.1.0 (T.A.S.K. Tactical Access Support Kit; offline map tool)`, optional contact
from Settings). Offline **Import MBTiles** always works, with no network at all.

## Rules (enforced in `task_maps/sources.py`, `download_permission`)

1. **tile.openstreetmap.org (and its subdomains) is always refused** for downloading, whatever a
   definition says. OSMF Tile Usage Policy §4: "Bulk downloading is any pre-emptive fetching of
   tiles other than those a user is actively viewing … Offline use is not permitted on
   tile.openstreetmap.org." — https://operations.osmfoundation.org/policies/tiles/ (read
   2026-10-10). A disabled, refused `osm-standard` entry is shipped so the refusal is visible.
2. A **packaged** source is offline-approved only with `offline_download_permitted = true`,
   `evidence`, `evidence_urls` (https) and `verified_on`. We only set this after reading the terms.
3. A **user** source (`~/.config/task-maps/sources.d/`) is usable when it sets
   `offline_download_permitted = true` **and** `user_attests_permission = true` — the user states
   they have permission (e.g. their own tile server). A user file cannot replace a packaged id.
4. Sources with `api_key_required = true` need `{api_key}` in the URL and a key stored with
   *Download → API key…* in `~/.config/task-maps/keys.toml` (mode 0600). Keys are substituted at
   request time and redacted from recorded errors; they are never logged.
5. Hard limits for any source: ≤ 10 requests/s, ≤ 4 connections, ≤ 500 000 tiles per job.
   HTTP 429/503 honour `Retry-After`.

## Shipped sources (verified 2026-10-10)

| id | Status | Evidence |
|---|---|---|
| `usgs-topo` — USGS Topo (The National Map) | **offline-approved**, 2 req/s, 2 connections, z0–16, ≤100 000 tiles/job | USGS FAQ: "Map services and data downloaded from The National Map are free and in the public domain. There are no restrictions; however, we request that the following acknowledgment … 'Map services and data available from U.S. Geological Survey, National Geospatial Program.'" https://www.usgs.gov/faqs/what-are-terms-uselicensing-map-services-and-data-national-map — service metadata `exportTilesAllowed: true`, `maxExportTilesCount: 100000`: https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer?f=pjson. No published rate limit; we chose 2 req/s. Coverage: US and territories in detail. |
| `usgs-imagery` — USGS Imagery Only | **offline-approved**, same limits | Same FAQ; https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer?f=pjson (`exportTilesAllowed: true`). |
| `osm-standard` — OpenStreetMap standard | **refused** (disabled) | OSMF policy §4 above. |

Checked but **not shipped** (terms not verified as permitting bulk/offline download by an app):
OpenTopoMap (https://opentopomap.org/about — use is allowed only as long as the servers are not
overloaded by mass downloads; larger projects should contact them), MapTiler, Thunderforest,
Stadia Maps (key-based commercial terms not verified). They can still be added as *user* sources
if the user has their own permission/agreement.

## Source file format (schema 1)

```toml
schema = 1
id = "my-tile-server"                 # [a-z][a-z0-9-]{1,47}
name = "My tile server (LAN)"
url = "http://192.168.1.10:8080/tile/{z}/{x}/{y}.png"   # {z} {x} {y} required; {api_key} optional
mechanism = "xyz"                     # xyz (y from top) | tms (y from bottom)
format = "png"                        # auto | png | jpg | webp
attribution = "© OpenStreetMap contributors"
license = "..."
usage_policy_url = "https://..."
offline_download_permitted = true
user_attests_permission = true        # user files only
evidence = "..."                      # packaged files: required for approval
evidence_urls = ["https://..."]
verified_on = "2026-10-10"
rate_limit = 2.0                      # requests per second (0.05–10)
max_concurrency = 2                   # 1–4
min_zoom = 0
max_zoom = 17
max_tiles_per_job = 100000
user_agent_required = true
api_key_required = false
enabled = true
coverage = "..."
avg_tile_bytes = 20000                # for estimates until real tiles exist
notes = "..."
```

Packaged sources must use https. Unknown keys are rejected; problems are listed, not fatal.
