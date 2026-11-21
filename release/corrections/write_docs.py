#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Writes the per-release documents into the staged zip directory. usage: write_docs.py REL STAGEDIR"""
import sys
from pathlib import Path

UNV = "**UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**"
COMMON_INSTALL = """## Quick start (on the Pi, as the desktop user, from the unpacked folder)
```
./preflight.sh                 # read-only; exit 0 = ready, 1 = a FAIL (nothing changed)
./install.sh                   # check only, prints the plan
./install.sh --install         # type the shown phrase; backup; one `sudo apt-get install --no-remove`
~/task-backups/<id>-<time>/rollback.sh ~/task-backups/<id>-<time> [--restore-data]
```
Full description of the checks and the backup: `INSTALLER.md`. No service is started or enabled; nothing autostarts.
"""

R = {}
R["sdr-0.2.3"] = dict(
    zip="TASK-Phase4G-SDRStudio-0.2.3", id="phase4g-sdr-0.2.3", title="Phase 4G SDR Studio + overlay framework (dataset-free), task-sdr 0.2.3",
    debs="`debs/task-sdr_0.2.3_all.deb`",
    rb="`rollback/task-sdr_0.2.2_all.deb`, `task-sdr_0.2.1_all.deb`, `task-sdr_0.2.0_all.deb`, `task-sdr_0.1.0_all.deb` (byte-identical to the earlier released packages)",
    paths=[("not installed", "0.2.3", "install.sh", "rollback leaves 0.2.3 installed (never removes); remove by hand if wanted", "01-fresh"),
           ("0.1.0 (current Pi)", "0.2.3", "install.sh", "rollback.sh → 0.1.0", "02 / 09"),
           ("0.2.0", "0.2.3", "install.sh", "rollback.sh → 0.2.0", "03 / 08"),
           ("0.2.1", "0.2.3", "install.sh", "rollback.sh → 0.2.1", "04 / 07"),
           ("0.2.2", "0.2.3", "install.sh", "rollback.sh → 0.2.2", "05 / 06"),
           ("0.2.3 or newer", "—", "preflight FAILs (no reinstall/downgrade)", "—", "10")],
    corrections=[
        "Version bump to **task-sdr 0.2.3** (code changed since 0.2.2). Same Depends as 0.2.2.",
        "M3 overlay framework, **dataset-free** (`OVERLAY-FRAMEWORK.md`): JSON format `task-sdr-overlay/1` (schema installed as `/usr/share/task-sdr/schema/overlay-v1.schema.json`), loaded at runtime from `/usr/share/task-sdr/overlays/` and `~/.local/share/task-sdr/overlays/` (neither is created by the package). Strict validation with whole-file rejection; background loading; Overlays tab with per-overlay toggles (**OFF by default**), search/filter, source info, stale/unverified/example badges and user annotations; markers on the spectrum; **receive-only tune only after confirmation**. \"Listed does not mean active\" and \"Receive capability is not transmit authorization\" are always shown.",
        "**No external dataset is included.** The example fixtures stay in `sdr/tests/fixtures/overlays/` (in `source/` only) and are **not** in the deb, so a fresh install shows no overlays at all until a separately reviewed data package or the user adds one. Licence status of candidate sources: `SOURCE-LICENSE-INVENTORY.md` (revision 3).",
        "Frequency audit (`FREQUENCY-AUDIT.md`, findings A1–A12): exact integer Hz everywhere; no 32-bit Qt signals; exact Decimal tuner parsing; strict prefs, bookmarks, presets, ignores and scanner input; RangeError (never a crash) for NaN/inf/float/str/bool; uint32 guard before librtlsdr. Per-receiver limits unchanged.",
        "Overlays are isolated from the scanner, bookmarks, presets and ignores (tested): toggles are in their own file `~/.config/task-sdr/overlays.json`; prefs.json gains no overlay keys, so a rollback to 0.2.2 or earlier reads it unchanged.",
        "Installer: the same hardened shared scripts as the other revisions (platform hard-fail arm64 + Debian 13 trixie, `bash -p` clean-environment re-exec, no overrides). `~/.local/share/task-sdr` (user annotations) is now backed up together with `~/.config/task-sdr`.",
    ],
    limits=[
        "Hardware: nothing measured on a Pi 5 or RTL-SDR Blog V4. " + UNV + ". The overlay UI was exercised offscreen only.",
        "No reviewed dataset exists yet. Overlays are useful only with user annotations until Phase B data (D1–D5, D9) is verified against the annual CFR and released separately.",
        "Hand-edited prefs.json: invalid bookmark/preset/ignore entries are now dropped individually on load, and disappear from the file on the next save.",
        "Rolling back to 0.2.2 or earlier: overlay toggles and annotations are kept on disk but unused (older versions ignore them).",
        "Rollback to 0.1.0 needs SoapySDR again (0.1.0 Depends on it); see APT-EXPECTED.md.",
    ],
    checklist=["Run `./preflight.sh`; save the output. Expect PASS; WARN only for SoapySDR auto-marking if applicable.",
               "Close SDR Studio. `./install.sh --install`, type the phrase, approve apt's own prompt.",
               "`dpkg-query -W task-sdr` shows 0.2.3; `ls /usr/share/task-sdr/` shows only `schema/` (no overlays, no data).",
               "Start SDR Studio by hand; no scan starts; the Overlays tab says 0 overlays loaded; bookmarks, presets and ignores are as before.",
               "Tune by typing `1766.000001M` (rejected as out of range) and `146.52` (accepted; display 00.146.520.000).",
               "Overlays tab: annotate the current frequency; it appears on the spectrum strip; click it, then cancel (no retune); click it, then confirm (retune, mode unchanged).",
               "Check that `~/.config/task-sdr/prefs.json` contains no overlay keys.",
               "Rollback drill (optional): `rollback.sh <backup>` → 0.2.2; check that SDR Studio 0.2.2 starts with the same bookmarks; reinstall 0.2.3."])
R["sdr-0.2.2"] = dict(
    zip="TASK-Phase4G-SDRStudio-0.2.2-r2", id="phase4g-sdr-0.2.2-r2", title="Phase 4G SDR Studio + Smart Scanner, task-sdr 0.2.2 (release r2)",
    debs="`debs/task-sdr_0.2.2_all.deb`", rb="`rollback/task-sdr_0.2.1_all.deb`, `task-sdr_0.2.0_all.deb`, `task-sdr_0.1.0_all.deb`",
    paths=[("not installed", "0.2.2", "install.sh", "rollback leaves 0.2.2 installed (never removes); remove by hand if wanted", "01-fresh"),
           ("0.1.0 (current Pi)", "0.2.2", "install.sh", "rollback.sh → 0.1.0", "02 / 07"),
           ("0.2.0", "0.2.2", "install.sh", "rollback.sh → 0.2.0", "03 / 06"),
           ("0.2.1", "0.2.2", "install.sh", "rollback.sh → 0.2.1", "04 / 05"),
           ("0.2.2 or newer", "—", "preflight FAILs (no reinstall/downgrade)", "—", "08")],
    corrections=[
        "Version bump to **task-sdr 0.2.2** (code changed since 0.2.1).",
        "1A Ignore tolerance per entry: exact 0 Hz by default; set in Hz or kHz; effective tolerance capped at (spacing−1)//2, so an adjacent channel is never suppressed (tested at the boundaries); Session vs Always clearly labelled; review list with Set tolerance / Make Always / Make Session / Remove.",
        "1A Lossless migration: 0.2.1 `scan_ignores` load as Always + exact. The legacy list is still written, so a rollback to 0.2.1 keeps the ignores (only the tolerances are lost).",
        "1B History actions: Retune, Ignore, Ignore always, Un-ignore, Add/Remove bookmark, Pin/Unpin, Clear unpinned, as buttons and a context menu. 50 entries, newest first, pins retained. Retune stops the scan and never touches recording.",
        "1C Silent-carrier release is now optional, **OFF by default**, configurable in seconds and labelled. When off, only the 4 s hold releases a channel. Scan/Pause/Resume/Skip follow one state table, tested for all 5 states × 5 commands.",
        "1D Docs (`SMART-SCANNER.md`): evidence split into synthetic tests / mocked driver / x86 bench / Pi 5 (PENDING) / V4 (PENDING); the real-world \"zero missed\" implication removed; physical measurement protocol P1–P8 with blank result tables. Bench re-run on 0.2.2 code (x86 only).",
        "2 Hardened installer (`INSTALLER.md`): simulation exit code, Remv/Purg, downgrades, broken deps, arch/OS checks, no autoremove, no apt-mark, SoapySDR warning only, backup of settings and dpkg state, verified rollback debs, typed confirmations, explicit tested rollback.",
    ],
    limits=[
        "Hardware: nothing measured on a Pi 5 or RTL-SDR Blog V4. " + UNV + ".",
        "One receiver: transmissions overlapping a lock or hold are missed. Real miss rates are unknown until protocol P5.",
        "Retune settle (one 8 ms block) not validated on hardware.",
        "SoapySDR has been optional (Suggests) since 0.2.0. If it was pulled in automatically by 0.1.0, a later `apt autoremove` (never run by this installer) could remove it. Preflight warns and prints the `apt-mark manual` command for you to decide on.",
        "Rolling back to 0.1.0 needs SoapySDR again (0.1.0 Depends on it). On a Pi where it is still installed, apt installs only task-sdr. Where it was removed, apt pulls about 40 SoapySDR packages from the Debian archive (observed scenario 07), which needs network access or a local mirror.",
    ],
    checklist=["Run `./preflight.sh`; save the output. Expect PASS; WARN only for SoapySDR auto-marking if applicable.",
               "Close SDR Studio. `./install.sh --install`, type the phrase, approve apt's own prompt.",
               "`dpkg-query -W task-sdr` shows 0.2.2; `~/task-backups/phase4g-sdr-0.2.2-*/` exists (0700).",
               "Start SDR Studio by hand; check that no scan starts by itself.",
               "Old ignores are listed as *Always, exact*. Add a 5 kHz ignore at 12.5 kHz step; effective shows 5 000 Hz; set 50 kHz → effective 6 249 Hz.",
               "Carrier timeout checkbox is OFF by default.",
               "History: Retune, Pin, Bookmark add/remove from the right-click menu.",
               "Run the measurement protocol P1–P8 in `SMART-SCANNER.md` §5 (receive only; never transmit) and fill in the tables.",
               "Rollback drill (optional): `rollback.sh <backup>`; check version; reinstall 0.2.2."])
R["sdr-0.2.0-r2"] = dict(
    zip="TASK-Phase4G-SDRStudio-0.2.0-r3", id="phase4g-sdr-0.2.0-r3", title="Phase 4G SDR Studio, task-sdr 0.2.0, installer revision r3",
    debs="`debs/task-sdr_0.2.0_all.deb` (byte-identical to the original 0.2.0 zip, sha256 50fd915c…)", rb="`rollback/task-sdr_0.1.0_all.deb`",
    paths=[("not installed", "0.2.0", "install.sh", "rollback leaves 0.2.0 installed (never removes)", "01-fresh"),
           ("0.1.0 (current Pi)", "0.2.0", "install.sh", "rollback.sh → 0.1.0", "02 / 03"),
           ("0.2.1 / 0.2.2", "—", "preflight FAILs (refuses downgrade). Use the 0.2.2 zip's rollback instead", "—", "04")],
    corrections=["**Installer-only revision.** The package is unchanged (same 0.2.0 deb), so the package version is NOT bumped. Only the zip revision is: r3 (r2 hardened the installer; r3 makes the host platform a hard requirement).",
                 "2 Hardened installer replaces the original 0.2.0 scripts (see `INSTALLER.md`), with the same checks as the other corrected releases.",
                 "Scanner corrections (1A–D) are NOT in 0.2.0. They are in task-sdr 0.2.2 (separate zip)."],
    limits=["Hardware: " + UNV + ".", "Same SoapySDR note as 0.2.2: optional since 0.2.0; warning only, never apt-mark.",
            "Rollback to 0.1.0 needs SoapySDR (observed scenario 03 pulls about 40 packages if it is absent)."],
    checklist=["`./preflight.sh` → PASS.", "Close SDR Studio; `./install.sh --install`; type the phrase.",
               "`dpkg-query -W task-sdr` → 0.2.0. Start by hand; tune a broadcast FM station (receive only).",
               "Optional rollback drill to 0.1.0."])
R["medical-0.3.6"] = dict(
    zip="TASK-Phase4F3-Medical-0.3.6-r2", id="phase4f3-medical-0.3.6-r2", title="Phase 4F.3 Medical, task-launcher 0.3.6 + task-resources 0.2.3 (release r2)",
    debs="`debs/task-launcher_0.3.6_all.deb`, `debs/task-resources_0.2.3_all.deb`",
    rb="`rollback/task-launcher_0.3.5_all.deb`, `task-launcher_0.3.4_all.deb`, `task-resources_0.2.2_all.deb`, `task-resources_0.2.1_all.deb`",
    paths=[("launcher 0.3.4 + resources 0.2.1 (current Pi)", "0.3.6 + 0.2.3", "install.sh", "rollback.sh → 0.3.4 + 0.2.1", "01 / 05"),
           ("launcher 0.3.5 + resources 0.2.2 (4F.3 0.3.5 zip)", "0.3.6 + 0.2.3", "install.sh", "rollback.sh → 0.3.5 + 0.2.2", "02 / 04"),
           ("launcher 0.3.4, no resources", "0.3.6 + 0.2.3", "install.sh", "launcher rolled back; resources left installed (never removed)", "03"),
           ("launcher < 0.3.4 or mesh < 0.3.1", "—", "preflight FAILs: install the earlier releases first", "—", "—"),
           ("newer than 0.3.6 / 0.2.3", "—", "preflight FAILs (no downgrade)", "—", "06")],
    corrections=["Version bumps: **task-launcher 0.3.6** and **task-resources 0.2.3** (code changed since 0.3.5 / 0.2.2).",
                 "3 SQLite: Medical's read-only access no longer creates or leaves `-wal`/`-shm` files. It uses a verified snapshot copy (content hash + stat, up to 3 retries) opened `immutable=1`; live `mode=ro` only when both side files already exist; side files are never deleted. Options and trade-offs: `MEDICAL-SQLITE.md`.",
                 "3 Medical refresh keeps the browser unless the snapshot is stale. A failing browser closes the DB. Shutdown is idempotent. Tested: no orphaned QtWebEngine processes or DB connections, DB and ZIM hashes unchanged, Medical + Resources at the same time.",
                 "3 Backup/rollback treats db+wal+shm as one set: consistent backup through the SQLite backup API; on restore, the current set is moved aside together.",
                 "2 Hardened installer (`INSTALLER.md`) with an added Medical DB check: preflight runs `integrity_check` on a private consistent copy of each Resources DB."],
    limits=["Hardware: " + UNV + " (Pi 5 display, WebEngine performance, SD-card I/O).",
            "If Medical holds a *live* connection when Resources (the last writer) closes, Resources' own -wal/-shm may stay until Resources next opens and closes the index. That is normal SQLite behaviour and documented.",
            "Snapshots of indexes > 1 GiB fall back to live `mode=ro`. Typical indexes are a few MB.",
            "Restart the launcher after installing; the installer never restarts it."],
    checklist=["Close Resources. `./preflight.sh` → PASS, including `integrity_check ... ok` for the index.",
               "`./install.sh --install`; type the phrase. Check `dpkg-query -W task-launcher task-resources` → 0.3.6 / 0.2.3.",
               "`ls -la ~/.local/share/task-resources/`: note the files. Open Medical, browse, lock/unlock the screen 3×, close it. List again: no new -wal/-shm created by Medical.",
               "Open Resources and Medical together; add a ZIM in Resources; Medical shows it after refresh.",
               "`pgrep -af QtWebEngineProcess` after closing the launcher → none.",
               "Optional rollback drill with `--restore-data`; check that `pre-rollback-*` holds the previous set."])


R["medical-reader-0.3.7"] = dict(
    zip="TASK-Phase4F3-MedicalReader-0.3.7", id="phase4f3-medical-reader-0.3.7", title="Phase 4F.3 Medical Reader Crash Repair, task-launcher 0.3.7 + task-resources 0.2.4",
    debs="`debs/task-launcher_0.3.7_all.deb`, `debs/task-resources_0.2.4_all.deb`",
    rb="`rollback/task-launcher_0.3.6_all.deb`, `task-launcher_0.3.5_all.deb`, `task-launcher_0.3.4_all.deb`, `task-resources_0.2.3_all.deb`, `task-resources_0.2.2_all.deb`, `task-resources_0.2.1_all.deb` (byte-identical to the earlier released packages)",
    paths=[("launcher 0.3.6 + resources 0.2.3 (crashing build)", "0.3.7 + 0.2.4", "install.sh", "rollback.sh → 0.3.6 + 0.2.3", "01 / 04"),
           ("launcher 0.3.4 + resources 0.2.1", "0.3.7 + 0.2.4", "install.sh", "rollback.sh → 0.3.4 + 0.2.1", "02 / 05"),
           ("launcher 0.3.6, no resources", "0.3.7 + 0.2.4", "install.sh", "launcher rolled back; resources left installed (never removed)", "03"),
           ("launcher < 0.3.4 or mesh < 0.3.1", "—", "preflight FAILs: install the earlier releases first", "—", "—"),
           ("newer than 0.3.7 / 0.2.4", "—", "preflight FAILs (no downgrade)", "—", "06")],
    corrections=["Version bumps: **task-launcher 0.3.7** and **task-resources 0.2.4**. Depends unchanged; launcher Suggests `task-resources (>= 0.2.4)`.",
                 "Crash fix (REPRODUCED on x86_64, see `MEDICAL-READER-RCA.md`): the launcher's auto-lock idle filter was installed application-wide; PySide wrapped a half-constructed `QWebEngineUrlRequestJob` and segfaulted on the first embedded Medical page. The filter is now attached per top-level window. Negative control: the new subprocess test crashes (-11) on 0.3.6 and passes on 0.3.7.",
                 "WebEngine crash guard: a marker is written before the first enhanced-reader load and removed after it succeeds. After a crash, `auto` mode opens the lightweight reader with a notice and a \"Try enhanced reader\" button; never retried automatically. No sandbox, environment, Qt/graphics or startup change.",
                 "Light reader: percent-encoded image/CSS paths are decoded; unsupported or missing images show a labelled placeholder naming the format; images scale to the reader width; bordered tables, right-floating infoboxes, full-width wikitables.",
                 "Read-only behaviour kept: navigation, bookmarks and search unchanged; tests confirm DB and ZIM hashes are unchanged. No migration. The backup now also copies `~/.local/state/task-launcher` (Medical bookmarks, guard file) and `~/.local/state/task-resources`."],
    limits=["Hardware: " + UNV + " (Pi 5, LXDE/X11, the real MDWiki ZIM). That the reproduced crash is the Pi crash is INFERRED from the identical code path.",
            "INFERRED: blank images on the Pi are likely WebP/SVG without the optional Qt plugins (`qt6-image-formats-plugins`, `qt6-svg-plugins`). Not added as dependencies; install them only with your approval.",
            "The out-of-process enhanced reader is a proposal only (RCA §5).",
            "Known pre-existing flake: resources `test_p4f3_rosnap` q08 occasionally fails under full-suite load only (passes alone and on the unchanged base commit). It passed in the logged run.",
            "Restart the launcher after installing; the installer never restarts it. Use `/usr/bin/python3` for manual checks (the shell `python3` may be a Starlink venv)."],
    checklist=["`sha256sum -c SHA256SUMS`; close Resources and the launcher; `./preflight.sh` → PASS.",
               "`./install.sh --install`; type the phrase. `dpkg-query -W task-launcher task-resources` → 0.3.7 / 0.2.4.",
               "Optional, with approval: `dpkg -l qt6-image-formats-plugins qt6-svg-plugins` and record whether they are installed (do not install them as part of this checklist).",
               "Start the launcher by hand; open Medical; open the MDWiki ZIM and 5 articles: no crash. `ls ~/.local/state/task-launcher/medical-webengine-guard.json` → absent after the first page loads.",
               "Images: record which ones render, which show a placeholder and the placeholder text. Tables: bordered, infobox on the right.",
               "Auto-lock with REAL input: idle until the lock appears; unlock; keyboard Tab moves the focus ring; mouse movement resets the idle timer, including over the Medical page.",
               "Bookmarks, back/forward and search work in Medical; Resources and Medical open together.",
               "Fallback drill (simulated crash marker; launcher closed; run in a terminal of the same LXDE session so the platform part of the fingerprint matches): `cd /usr/share/task-resources && /usr/bin/python3 -I -c 'import sys;sys.path.insert(0,\".\");from pathlib import Path;from task_resources.viewer.guard import CrashGuard;p=Path.home()/\".local/state/task-launcher/medical-webengine-guard.json\";p.parent.mkdir(parents=True,exist_ok=True);CrashGuard(p,host=\"task-launcher 0.3.7\",pid=999999999).arm(\"drill\")'`. Start the launcher; open Medical: lightweight reader with the notice, NO automatic retry. (Reset at any time: delete that file.)",
               "Press \"Try enhanced reader\": the page opens in the enhanced reader; the guard file is removed after success; the next start uses the enhanced reader again.",
               "`pgrep -af QtWebEngineProcess` after closing the launcher → none.",
               "Optional rollback drill: `rollback.sh` → 0.3.6 / 0.2.3 (expect the original crash to return on that version)."])

HOST_FIX = ("**Release revision (2026-10-14): host platform is now a HARD requirement** in preflight, install and rollback "
            "(one shared function, `tg_require_host`). Required: `dpkg --print-architecture` = arm64 and a strictly parsed "
            "`/etc/os-release` with ID=debian, VERSION_ID=13, VERSION_CODENAME=trixie (64-bit Raspberry Pi OS trixie reports "
            "exactly this). Anything else, including a missing or malformed file, exits 1 with found / expected / why, before any "
            "apt call or backup. The installer test-mode overrides were REMOVED: the scripts re-run in a whitelisted environment "
            "under `bash -p`, and tests use a private namespace fixture instead (INSTALLER.md, \"Threat model\"). The app "
            "packages are byte-identical to the previous revision.")
HOST_STEP = ("Before anything else, record `dpkg --print-architecture` and `cat /etc/os-release`. Expected: `arm64`, "
             "`ID=debian`, `VERSION_ID=\"13\"`, `VERSION_CODENAME=trixie`. If they differ, stop: preflight will reject the host.")
HOST_LIMIT = ("The accepted os-release values for Raspberry Pi OS come from user-posted os-release files from real systems, "
              "not an official specification. The Pi checklist records the real file first.")
for _k, _r in R.items():
    if _k != "sdr-0.2.3":                     # 0.2.3 is a new package version; its notes describe the installer
        _r["corrections"].insert(0, HOST_FIX)
    _r["checklist"].insert(0, HOST_STEP)
    _r["limits"].append(HOST_LIMIT)


def main():
    rel, st = sys.argv[1], Path(sys.argv[2])
    r = R[rel]
    rows = "\n".join(f"| {a} | {b} | {c} | {d} | {e} |" for a, b, c, d, e in r["paths"])
    (st / "README.md").write_text(f"""# T.A.S.K. {r['title']}

Release id: `{r['id']}`. Licence GPL-3.0-or-later (`LICENSE`), © 2026 Joshua Sturtz. Maintainer: T.A.S.K. Development Team <TBD-maintainer-email>.
Receive-only / offline software. **Not installed or tested on a Raspberry Pi.** Hardware: {UNV}.

| Contents | |
|---|---|
| Packages | {r['debs']} |
| Rollback packages | {r['rb']} |
| Installer | `preflight.sh`, `install.sh`, `rollback.sh`, `task-guard.sh`, `release.conf`, `tools/` (`INSTALLER.md`) |
| Notes | `RELEASE-NOTES.md` (corrections, limitations, risks), `PI-CHECKLIST.md` |
| apt | `apt-sim/` (OBSERVED, private arm64 simulation on the build box), `APT-EXPECTED.md` (EXPECTED on a Pi) |
| Tests | `TEST-RESULTS.md`, `test-logs/` |
| Source | `source/` (git archive of the exact commit) |
| Checksums | `SHA256SUMS` (verify: `sha256sum -c SHA256SUMS`) |

{COMMON_INSTALL}
## Upgrade and rollback paths
| Installed now | Result | How | Rollback | Observed sim (`apt-sim/`) |
|---|---|---|---|---|
{rows}
""")
    (st / "RELEASE-NOTES.md").write_text(f"# Release notes: {r['title']}\n\n## Corrections in this release\n"
        + "\n".join(f"{i}. {c}" for i, c in enumerate(r["corrections"], 1))
        + "\n\n## Limitations\n" + "\n".join(f"* {x}" for x in r["limits"])
        + "\n\n## Risks and how they are contained\n"
        "| Risk | Containment |\n|---|---|\n"
        "| apt would remove or downgrade something | Preflight FAILs on any Remv/Purg/downgrade; install uses `--no-remove`; apt asks again (no `-y`) |\n"
        "| Partial install | Version check afterwards; backup + `rollback.sh` with verified debs |\n"
        "| Lost settings or data | Settings and SQLite backed up before install; restore moves current files aside, never deletes |\n"
        "| Unintended service or radio activity | No maintainer scripts, no services, no autostart, receive only |\n"
        "| Simulation differs from the Pi | Observed sims use real trixie arm64 lists but synthetic installed states. The Pi's own preflight is the authority |\n")
    (st / "PI-CHECKLIST.md").write_text(f"# Pi checklist: {r['title']}\n\nAll steps by a person on the Pi. Nothing here transmits. Results go in the table.\n\n"
        "| # | Step | Result | Date / tester |\n|---|---|---|---|\n"
        + "\n".join(f"| {i} | {s} | | |" for i, s in enumerate(r["checklist"], 1)) + "\n")


if __name__ == "__main__":
    main()
