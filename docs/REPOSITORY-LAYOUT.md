# Repository layout

The tree keeps every existing package directory, Python import name and Debian
package name exactly as installed on the development Pi, so nothing breaks and
history stays traceable. The conceptual layout from the release directive
(`core/ modules/ gui/ hardware/ …`) is mapped below; physically moving packages
into it is a separate, approval-gated migration (see docs/APPROVALS-NEEDED.md).

| Path | Contents | Directive area | Debian package | Import name |
|---|---|---|---|---|
| `task_core/`, `task_core_migrate/` | Core daemon, admin CLI, R.A.I.N. migration | core/ | task-core, task-core-compat | `task_core`, `task_core_migrate` |
| `tests/` | Core test suite (+ golden transcripts) | tests/ | — | — |
| `share/` | Core device and module manifests | core/ | task-core | — |
| `packaging/task-core/` | task-core.service | packaging/debian/, services/ | task-core | — |
| `comms/` | Shared comms library | core/ | python3-task-comms | `task_comms` |
| `launcher/` | Launcher + built-in views + tiles (`task_launcher/data/apps.d`) | gui/ | task-launcher | `task_launcher` |
| `console/` | Devices app | modules/ | task-console | `task_console` |
| `mesh/` | Mesh Network (own pyproject, vendored wheels, systemd user unit) | modules/, services/ | task-mesh | `task_mesh` |
| `maps/` | Maps & GPS | modules/ | task-maps | `task_maps` |
| `aprs/` | Radio / APRS | modules/ | task-aprs | `task_aprs` |
| `sdr/` | SDR Studio (+ public-domain eCFR/NWS source snapshots for the frequency audit) | modules/ | task-sdr | `task_sdr` |
| `resources/` | Offline Library & Medical Reader | modules/ | task-resources | `task_resources` |
| `platform/` | Cross-platform abstractions (new, experimental) | hardware/common, hardware/linux, hardware/windows | not packaged yet | `task_platform` |
| `installers/raspberry-pi/` | Pi installer (new, dry run) | installers/raspberry-pi | not packaged yet | `task_installer` |
| `installers/windows/` | Windows installer plan | installers/windows | — | — |
| `release/` | Existing deterministic `.deb` builders, hardened bash installer framework (`release/common`) and per-release configs | packaging/debian, scripts/ | — | — |
| `deploy/` | Legacy R.A.I.N. Phase 1–2 deploy/update scripts (kept: tests and migration history depend on them) | scripts/ | — | — |
| `scripts/` | Test runner, private-data scanner, mesh-alert recipe | scripts/ | — | — |
| `docs/` | Architecture, design (Radio Phase 5A, Firmware Manager), provenance, engineering history | docs/ | — | — |
| `.github/` | Issue and PR templates | community | — | — |
| *(not in git)* `releases/` | Built artifacts go to **GitHub Releases**, never committed | releases/ | — | — |
