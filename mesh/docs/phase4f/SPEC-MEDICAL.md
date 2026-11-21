<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# SPEC — Medical via a supported Resources category filter (Phase 4H)

* Add to task-resources a **supported** entry point: `task-resources --view category:Medical` (argparse choice, validated,
  documented, tested) that opens the library filtered by index category "Medical" (resource_category table already exists).
  No undocumented `--category` hack.
* Launcher manifest 070 keeps id **task.medical**, `[launch] builtin = "medical"` stays as fallback; add
  `exec = ["/usr/bin/task-resources", "--view", "category:Medical"]` used only when task-resources >= 0.3.0 reports
  support (`--capabilities` JSON), otherwise the built-in MedicalWindow opens.
* Reference only; patient data remains out of scope (Core keeps refusing medical.patients.*).
* Regression tests: Medical and Library tiles present with ids task.medical/task.library after (a) upgrade from 0.3.2,
  (b) reinstall, (c) simulated reboot (fresh registry build from tiles.json); fallback used when task-resources absent or old;
  tiles.json placement preserved.
