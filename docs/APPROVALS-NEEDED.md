# Decisions that need the maintainer's approval

Nothing below has been done. Each item needs Joshua Sturtz's explicit decision.

| # | Decision | Recommendation |
|---|---|---|
| 1 | **License** | Confirm GPL-3.0-or-later (already on every file; OSI-approved; compatible with the vendored GPL-3.0-only meshtastic, MIT/BSD/ISC components). Copyright line "© 2026 Joshua Sturtz and T.A.S.K. contributors". |
| 2 | task-mesh copyright holder and `Source:` field | Change "T.A.S.K. Mesh Operations contributors" → "Joshua Sturtz and T.A.S.K. contributors" and `example.invalid` → the GitHub URL, in a task-mesh 0.3.2 release. |
| 3 | Maintainer / security / conduct contact e-mail | Not invented. Provide one, or use GitHub private vulnerability reporting only. |
| 4 | Donation platform | Optional only. Options: GitHub Sponsors, Liberapay, Open Collective (transparent ledger). Add `.github/FUNDING.yml` once chosen. |
| 5 | Version numbering | Keep per-package Debian versions; tag platform releases `vYYYY.MM-alphaN` or `v0.1.0-alpha.1`. Recommend `v0.1.0-alpha.1` "Public Alpha 1". |
| 6 | Release name/stage | "Public Alpha" (not Beta): installer is dry-run, several modules lack hardware acceptance, no clean-Pi test yet. |
| 7 | Publishing | Pushing this tree to `TASK-Preparedness/TASK`, history (fresh single commit vs. importing development history), commit author identity, enabling Issues/Discussions/private vulnerability reporting. |
| 8 | Engineering history docs | Keep `docs/engineering-history/` (development record, Pi-specific notes, usernames genericised) or drop it from the public tree. |
| 9 | Physical layout migration | Keep current package directories (recommended) vs. moving into `core/ modules/ gui/ …` (breaks builders/tests; needs a migration). |
| 10 | task-mesh 0.3.2 | Release the maintained audible notifier as 0.3.2 (no behaviour change vs. the Pi) — install on the Pi only with separate approval. |
| 11 | Mesh alert WAV | Keep shipping the recipe only (recommended) vs. shipping the CC-BY-SA WAV with attribution. |
| 12 | task-core 0.3.1 lock fix | Include the unreleased `phase4c-fix-lock` change in the public tree or keep 0.3.0 as installed. |
| 13 | Version-string fixes | Align `task_core.__version__` (0.2.1→0.3.0) and `sdr/pyproject.toml` (0.2.2→0.2.4) — code change, needs a package rebuild. |
| 14 | Vendored wheels in git | Keep the four pinned wheels (~0.5 MB, offline reproducible builds — recommended) or fetch at build time. |
| 15 | Real installer execution | When validated packages exist: sudo-in-terminal vs. a minimal polkit helper for privileged steps (never a root GUI). |
| 16 | Clean-Pi test hardware | A spare SD card / Pi for install/upgrade/remove validation. |
| 17 | Windows work | Approve Milestone E start, CI on GitHub Actions, PyInstaller + NSIS. |
| 18 | Still pending from earlier | Seven Radio transmit questions, Milestone B coding approval, Firmware Manager questions and per-step Heltec approvals (unchanged). |
