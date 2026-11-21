# Phase 4F.2 — Native Medical view (task-launcher 0.3.4)

## Audit findings
| Area | Finding |
|---|---|
| Manifest parsing (`registry/manifest.py`) | `070-medical.toml` declares `[launch] builtin = "medical"`, readiness `medical`. A builtin may carry `exec` only if it is in `EXEC_FALLBACK_BUILTINS = ("devices","radio","library")`. Otherwise `parse_doc` raises `ManifestError("builtin 'medical' does not take 'exec'")`. |
| Why the tile disappeared | The manual edit added `exec=/usr/bin/task-resources` to the Medical manifest. That made the manifest invalid, so the registry dropped it (an invalid manifest yields no tile). The shipped manifest is correct and was not changed. Test M14 guards both behaviours. |
| Readiness | `services/medical.py` (unchanged) matches Kiwix library books by keyword and lists IIAB modules plus configured folders. It runs in the probe worker, so the UI never blocks. |
| Builtin routing (why the legacy path) | `MainWindow.activate()` sent every builtin in `NATIVE_WINDOWS` (library, radio, weather, medical) to `open_builtin()`. That calls `native_windows.create()`, which builds `_Base(QWidget)` with `Qt.WindowType.Window`, i.e. a **separate top-level window**. There was no in-window navigation: `setCentralWidget(self.home)`. |
| Tile registration | 12 shipped `app:task.*` tiles; unchanged (M13). |
| Resources entry points | `task-resources` has no CLI option to open a category or item. Its `Index` opens `index.sqlite` **read-write** (DDL, WAL pragma, meta insert) and its UI is a full `QMainWindow`. Embedding either would write to the Resources DB and pull in a second application shell. |

## Fix (smallest)
* `MainWindow` now holds a `QStackedWidget` view stack, with Home as page 0. `open_view(name)` creates a view once, then reuses it (refreshing on reopen). `go_back()` and `go_home()` navigate. A lock always returns to Home, under the lock overlay.
* `activate()` routes `builtin in NATIVE_VIEWS = ("medical",)` to `open_view`. The other builtins are unchanged. `open_builtin("medical")` (the legacy window) is kept as the fallback if the view fails to build.
* `ui/medical_view.py` (`MedicalView`) is the native shell: Back, Home, Refresh, a disclaimer, a list and an empty state. Sources:
  * the T.A.S.K. Resources index, category "Medical" (case-insensitive), read by `services/medical_index.py`. That module uses the *same* schema-1 tables as task-resources' own `Index.list(category=…)`, via SQLite `mode=ro`. It refuses newer schemas and never scans or reindexes.
  * the existing medical probe (Kiwix books, IIAB modules, configured folders).
  Only items actually present in those indexes are shown. There are no placeholders.
* Content rendering stays outside the shell:
  * Kiwix books → the built-in Kiwix viewer (localhost);
  * PDF/EPUB/TXT/HTML files → the desktop reader via `xdg-open` (argv);
  * Resources ZIM items → T.A.S.K. Resources, through the Library tile's own route (single instance).
  **Needs an external reader:** non-Kiwix files. Opening one specific Resources item directly would need a future `task-resources --open ID` option (not added; Resources unchanged).
* No pop-out: it was optional, and was omitted to avoid duplicate-window cases.

## Why the Resources Python widgets were not embedded directly
Reusing `task_resources.index.Index` would execute DDL and `PRAGMA journal_mode=WAL` against the user's index on every open. That breaks "no DB changes". The read-only adapter keeps the model contract (category filter, title override, duplicates hidden) without writing. task-resources is therefore **unchanged** and is not bumped.

## Unchanged
Manifests, the 12 tiles, Core/auth, task-core.service, Kiwix services, /library, ZIMs, the Resources index, task-resources, task-mesh and comms.
