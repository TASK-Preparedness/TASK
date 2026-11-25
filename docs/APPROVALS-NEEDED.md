# Decisions that need the maintainer's approval

> Updated 2026-11-24. Several items were decided by Joshua Sturtz on
> 2026-11-24 (recorded below). Package updates task-mesh 0.3.2~alpha1,
> task-console 0.2.1~alpha1 and launcher 0.3.8 were **approved on
> 2026-11-23 for packaging, isolated testing and volunteer-testing
> packages only**. They are not validated on a physical Raspberry Pi.
> Publication of the repository, the git tag and the GitHub pre-release
> still awaits his approval of the final release bundle.

| # | Decision | Status |
|---|---|---|
| 1 | **License** | **DECIDED 2026-11-24 — Option A.** Own code is GPL-3.0-or-later. The `task-mesh` package as a whole is GPL-3.0 because it bundles meshtastic (GPL-3.0-only). Separate [TRADEMARK.md](../TRADEMARK.md) policy. Copyright line: `Copyright (C) 2026 Joshua Sturtz and T.A.S.K. contributors` (his name alone on his own files). Inbound=outbound with DCO 1.1 sign-off; no CLA. Attorney review is still recommended and has not been obtained. |
| 2 | task-mesh copyright holder and `Source:` field | **Open for a later package rebuild.** The published alpha `.deb` checksums are frozen, so package copyright/`Source:` placeholders are left as they were in the volunteer-test packages. |
| 3 | Maintainer / security / conduct contact | **DECIDED 2026-11-24.** Security reports: GitHub private vulnerability reporting (Security tab → Report a vulnerability). General support: GitHub Issues. No project email address. Enabling private vulnerability reporting is the first publication step (see the unpublished push-commands note in the approval bundle). |
| 4 | Donation platform | **DECIDED 2026-11-24 (updated later the same day).** Voluntary funding page: <https://buymeacoffee.com/t.a.s.k.prepardness> (URL used exactly as provided). `.github/FUNDING.yml` lists that URL under GitHub's `custom` key. Contributions are entirely optional. No software features are or will be restricted based on financial contributions. Contributions support development time, equipment, testing, maintenance and future improvements. |
| 5 | Version numbering | **DECIDED 2026-11-24.** Platform tag `v0.1.0-alpha.1`. Per-package Debian versions are unchanged. |
| 6 | Release name/stage | **DECIDED 2026-11-24.** Experimental public alpha pre-release. Clearly disclose that the packages have **not** been validated on a physical Raspberry Pi. |
| 7 | Publishing | **DECIDED in part 2026-11-24; not executed.** Build on top of the existing `origin/main` README-only commit (fast-forward; no force-push). Git author: Joshua Sturtz and his verified GitHub no-reply address. Do not rewrite published history. Enable Issues (and Discussions if wanted) and private vulnerability reporting when publishing. **The push, tag and GitHub pre-release themselves still need explicit approval of the final bundle.** |
| 8 | Engineering history docs | **DECIDED 2026-11-24.** `docs/engineering-history/` is not in the public tree. A private copy is kept outside the repository. The five SDR Studio notes that already ship in the `task-sdr` package remain under `sdr/docs/`. |
| 9 | Physical layout migration | **Open.** Keep current package directories (recommended) vs. moving into `core/ modules/ gui/ …` (breaks builders/tests; needs a migration). |
| 10 | task-mesh 0.3.2 | Superseded by #19 until a Pi test passes. Do not install on the working Pi without a separate approval. |
| 11 | Mesh alert WAV | **Open.** Keep shipping the recipe only (recommended) vs. shipping the CC-BY-SA WAV with attribution. |
| 12 | task-core 0.3.1 lock fix | **Open.** Include the unreleased `phase4c-fix-lock` change in the public tree or keep 0.3.0 as installed. |
| 13 | Version-string fixes | **Open.** Align `task_core.__version__` (0.2.1→0.3.0) and `sdr/pyproject.toml` (0.2.2→0.2.4) — code change, needs a package rebuild. |
| 14 | Vendored wheels in git | **Open.** Keep the four pinned wheels (~0.5 MB, offline reproducible builds — recommended) or fetch at build time. |
| 15 | Real installer execution | **Open.** When validated packages exist: sudo-in-terminal vs. a minimal polkit helper for privileged steps (never a root GUI). |
| 16 | Clean-Pi test hardware | **Open.** A spare SD card / Pi for install/upgrade/remove validation. Never the working Pi. |
| 17 | Windows work | **Open.** Approve Milestone E start, CI on GitHub Actions, PyInstaller + NSIS. |
| 18 | Still pending from earlier | **Open.** Seven Radio transmit questions, Firmware Manager questions and per-step Heltec approvals (unchanged). |
| 19 | task-mesh **0.3.2~alpha1** (Milestone B) | **APPROVED 2026-11-23 for packaging, building and isolated testing only.** The `~alpha1` pre-release sorts below 0.3.2. Built and chroot-tested, not installed anywhere. Supersedes the plain "0.3.2" in #10 until a Pi test passes. |
| 20 | task-console **0.2.1~alpha1** (Milestone B) | **APPROVED 2026-11-23 for packaging, building and isolated testing only.** Dependency fix (`python3-pyside6.qtnetwork`). Packaging-only. |
| 21 | task-launcher **0.3.8** | **APPROVED 2026-11-23 for packaging, building and isolated testing only; merged and built.** Bundle: the Windows portability patch (`installers/windows/patches/`, Linux tests unchanged) and preferring `/usr/bin/task-console` over `/usr/local/bin` in `090-devices.toml`. |
| 22 | Clean-Pi package test | **Open.** Install, upgrade and remove the Milestone B bundle on a spare SD card (not the working Pi). Needed before the installer may execute anything. |
| 23 | Pi `dpkg-query` of dependency versions | **Received 2026-11-23** and recorded in `packaging/debian/reference/pi-dpkg-baseline-20261122.txt`. Exact pins for the Milestone D offline bundle still need to be written from that output. |
| 24 | Windows test machine | **Open.** A Windows 11 x64 machine/VM to run `installers/windows/build_windows.py` natively. The Wine build is not a Windows test. |
