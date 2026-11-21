<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# SPEC — T.A.S.K. Inventory (Phase 4G, task-inventory 0.1.0)

Status: **spec only, no code** (4F is test-ready but not hardware-tested; inventory code deferred to keep 4F isolated).

## Storage
* Separate DB: `~/.local/share/task-inventory/inventory.sqlite3`, 0600, WAL, schema version table, migrations
  numbered; never shares a file with mesh/resources/core.
* Tables: `item`(id, uuid, name, category_id, subcategory, description, quantity REAL, unit, min_quantity,
  location_id, container, condition [new|good|worn|damaged|expired], expires_on, acquired_on, cost, currency,
  supplier, part_number, serial_number, barcode, weight_g, notes, tags, photo_path, created_at, updated_at,
  created_by, updated_by, deleted_at), `category`, `location`(hierarchy: parent_id), `movement`(item_id, delta,
  reason [use|restock|transfer|loss|adjust|expire], from_location, to_location, at, by, note),
  `kit`/`kit_item` (bundles, e.g. go-bag), `attachment`, `audit`(append-only, actor, action, before/after json).
## Operations
add / edit / duplicate / soft-delete / restore; adjust quantity with reason (writes movement); transfer between
locations; check-out/check-in; kits (build, verify completeness); low-stock and expiring-soon views (N days);
search (FTS5 over name/description/tags/notes) and filters (category, location, condition, expiry, low stock);
sort any column; bulk edit (category/location/tags); undo last change (from audit).
## UI
Native PySide6 table (QTableView + model, sortable, column chooser, saved views), detail side panel, touch-sized
rows for the 7" screen, barcode field accepts USB HID scanner input. Offline only.
## Import / export / backup
CSV import with column mapping + dry-run preview + per-row errors; CSV/JSON export (filtered or all);
backup = SQLite online backup API to timestamped file in ~/.local/share/task-inventory/backups (keep N),
restore with confirmation; no cloud.
## Auth
Viewing: public by default (configurable). **Edits enforced in the inventory service layer** against a Core session
role (operator+; delete/restore/import: administrator), never by hiding buttons only. Every write audited.
## Extension points
`task_inventory.hooks`: on_item_changed, on_low_stock (→ comms notification source "inventory"),
custom field definitions (typed JSON in item.extra), category presets packs (TOML), label printer interface (stub).
## Tests (minimum)
schema/migration, 0600, CRUD+audit, movement math, low-stock/expiry, CSV import dry-run/errors, export round-trip,
backup/restore, role enforced in service (UI bypass refused), FTS search, launcher tile added without changing the 12.
