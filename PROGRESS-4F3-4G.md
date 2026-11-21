# PROGRESS — Phase 4F.3 Medical + 4G SDR Studio (branch phase4f3)
- [x] Resources 0.2.2: read-only Index/Library mode, classify.py (medical rules), ui/browser.py shared
      ResourceBrowser/ReaderPane, MainWindow composes it; hang fix (viewers reused + closed on shutdown,
      downloads UI stops polling closed manager); slow test marked; pytest timeout config. Suite 130 passed, 1 deselected (slow), x stable.
- [x] Launcher 0.3.5 embed (314 passed, 13 skipped; A01–A12 + 3 extra pass)
- [x] Packaged /workspace/TASK-Phase4F3-Medical-0.3.5.zip sha256 8dad59ca… (launcher deb e7e004de…, resources deb d731e48b…)
- [~] 4G M1 SDR Studio: code+34 tests pass (commit), packaging pending

## 4G M1 — PACKAGED
- `/workspace/TASK-Phase4G-SDRStudio-0.2.0.zip`: sha256 e15ba708aa9beb386f88ea676aa874b22f4d2f8f419df71539605e924ca012da
- task-sdr_0.2.0_all.deb: 50fd915ca6ab9f5c4e442d308bfa29c06f32174fb29045b76efae41eda86be27
- Tests: 34 passed (source, and again against the extracted deb tree). Protection and ref checks OK.
- Next: M2 Smart Scanner (not started).

## 4G M2 Smart Scanner (task-sdr 0.2.1)
- [x] scanner.py, sim_band.py, ui/scanner_panel.py, engine.scan_step; 48 tests pass (14 new)
- [x] benchmarks (light/heavy/5 ms retune: 0 missed while sweeping), docs, M3 data-source list
- [x] PACKAGED: /workspace/TASK-Phase4G-SDRStudio-0.2.1.zip sha256 0e4364790a8200836cfb1c6781bbb3ed08ec2d7111f2453f344aaaf806b17b05
      task-sdr_0.2.1_all.deb 26e8365393c045c748b879ae9f08286c2bb04c1d1a11cd70e4df2e6addb4a07f; rollback 0.2.0 (50fd915c…)
- M3 not started (by instruction). M4 not started.

## Corrections directive (9:09 PM)
- [x] 1A-C scanner 0.2.2 code + 36 new tests (84 pass)
- [x] 3 Medical SQLite code+tests (launcher 0.3.6, resources 0.2.3)  - [ ] 1D docs  - [ ] 2 installer hardening  - [ ] packaging  - [ ] M3

### Corrections, packaged (2026-10-13 21:55 ET), commit 9d24c42 (source in each zip)
| Zip | sha256 |
|---|---|
| TASK-Phase4F3-Medical-0.3.6.zip | aa2408ec0395efcbbc8f8639a4eebb9b3c6f98fb0e9856b56a131442a7d2228a |
| TASK-Phase4G-SDRStudio-0.2.0-r2.zip | 9b546bb0645d2297a1ab9cba17e3f2d6012f9ea264f000b4d8afac63f48940e4 |
| TASK-Phase4G-SDRStudio-0.2.2.zip | 70f42fc2fb30a30adac46f9a5732f3efae92ba4a015fc8b531484763b2441201 |

debs: task-launcher 0.3.6 d2274811…, task-resources 0.2.3 701f1f1f…, task-sdr 0.2.2 9919c5a0…, task-sdr 0.2.0 unchanged 50fd915c… (all reproducible).
Done: 1A–D, 2, 3, 5, 6. Tests: sdr 84 · resources 140 + 1 slow · launcher 318 (13 opt-in render skips) · installers 25 · 19 observed arm64 apt sims as expected. Protected files and refs unchanged.
Next: M3 (SOURCE-LICENSE-INVENTORY.md first). Hardware: UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.

### 2026-10-14: host platform hard requirement, revisions (commit a2e2ccb)
| Zip | sha256 |
|---|---|
| TASK-Phase4F3-Medical-0.3.6-r2.zip | 9450fb6e34b5e17d258b9deca0865d8709bf4f43c5c58a5bb1a2fab7c0f8f741 |
| TASK-Phase4G-SDRStudio-0.2.0-r3.zip | 1ffde2eef39d76455cc9e171d07dc1bf177427c8acec7dbf38317f3529a2f1d4 |
| TASK-Phase4G-SDRStudio-0.2.2-r2.zip | 5b496f1208b19f626e8149e438244ac2642be30d6b60e0a812e7a1f790b81d5e |
App/rollback debs byte-identical to the previous revisions. Installer 105 passed; sdr 84; resources 140+1; launcher 318 (13 opt-in skips); 19/19 arm64 sims as expected.

## 2026-10-15: task-sdr 0.2.3 (dataset-free overlay framework + frequency audit)
- Commits 0e92337 (framework), c280c7f (strict 64-bit Hz audit), 35797f4 (release). Inventory r3 with FAA D18 = c3f59c6.
- Zip /workspace/TASK-Phase4G-SDRStudio-0.2.3.zip sha256 9d74c16a9c368e1b2d95a2eafca43e365d45dabd0936ea7bfbf3fbadf3dce128; deb 7c45fa52… (reproducible).
- Tests: sdr 274, installer 107, launcher 318 (+13 skipped), resources 140+1, apt sims 11/11. Nothing on the Pi.
