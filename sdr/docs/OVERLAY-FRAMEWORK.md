# SDR Studio overlay framework (M3 Phase A): status

**Packaging decision (task-sdr 0.2.3):** the deb ships the code and the schema
(`/usr/share/task-sdr/schema/overlay-v1.schema.json`) only. It does **not** create `/usr/share/task-sdr/overlays/`
and contains **no dataset and no fixture**. The EXAMPLE fixtures live only in `sdr/tests/fixtures/overlays/`
(tests and source archive). A test (o02) checks that no dataset is in the package tree, and the release check
lists the deb contents.

This is source-level work on branch phase4f3. **No external dataset is included or packaged.** Only the test
fixtures in `sdr/tests/fixtures/overlays/` exist, all marked EXAMPLE (ids `example-*`, `"example": true`,
`https://example.invalid/` URLs, placeholder values). Nothing was installed or run on the Pi.
UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST (the UI was exercised offscreen only).

- Format: `sdr/overlays/schema/overlay-v1.schema.json` (`task-sdr-overlay/1`). The authoritative validator is `sdr/task_sdr/overlays.py`.
- Load paths: `/usr/share/task-sdr/overlays/*.json` (system) and `~/.local/share/task-sdr/overlays/*.json` (user). Data is read at runtime, so no rebuild is needed.
- Types: allocation, channel_plan, station_record, user_annotation (user_annotation is accepted from the user directory only).
- Items: `range` (start_hz < end_hz) and `marker` (freq_hz, optional bandwidth_hz), plus label, ref, notes and tags.
- Frequencies are integer Hz only, 1 Hz to 6 GHz. Floats, strings and booleans are rejected.
- Provenance: source{agency,citation,url(https)}, publication_date, retrieved, last_verified (null = UNVERIFIED), stale_after_days (default 365), version, attribution, example.
- A whole file is rejected on any error: unknown keys, duplicate JSON keys, NaN/Infinity, bad or future dates, out-of-bounds values, duplicate items, more than 5000 items, more than 2 MiB, symlinks or non-regular files, a user file reusing a system id. Reasons are shown in the panel.
- Loading runs on a background thread and results are delivered to the UI through a queued signal. Overlays start OFF. Per-overlay toggles are stored in `~/.config/task-sdr/overlays.json` (0600); prefs.json is unchanged.
- The UI is the Overlays tab next to Scanner. It has notes ("Listed does not mean active", "Receive capability is not transmit authorization"), toggles with EXAMPLE/UNVERIFIED/STALE/USER badges, search (text or frequency) and a type filter, a source-info panel (links are never opened), and buttons to annotate the current frequency, rename and remove (own annotations only), and reload.
- Spectrum: an overlay strip shows ranges and markers. Clicking an overlay asks for confirmation, then makes a receive-only tune through the normal `MainWindow.tune` path. The device range check still applies; mode and bandwidth are kept. A plain click elsewhere tunes as before.
- There is no TX code and no subprocess or network calls (enforced by test o31).
- Tests: `sdr/tests/test_overlays.py` has 91 tests. The full sdr suite is 175 passed (the 84 previous tests unchanged).
