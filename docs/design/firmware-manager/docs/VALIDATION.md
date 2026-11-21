# Validation record — Milestone A r2

2026-11-08 (EST). Documentation-only validation; no application/hardware claims.

## Actually performed on the development box

- Created a new isolated local Git repository at `/workspace/task-firmware-wt`, branch `phase-fwmgr`.
- Read public upstream/Debian documentation and license texts; recorded source links, revision evidence, limitations and unsupported/unknown cells.
- Wrote Markdown research/architecture documents only. No firmware binaries downloaded, no executable application/installer/flashing code added.
- PASS: local documentation audit found all 15 expected Markdown documents, valid local relative links, direct source-label numbers within S01–S34, and the required unverified hardware warning in every document. PASS: fenced-shell snippets parse with `bash -n` (syntax only, not execution), Markdown fences are balanced, and firmware/client/hash unknowns plus non-flashing ROM read flags are explicit. This audit does not test command behavior, remote URL liveness or hardware facts.
- Created ZIP from committed tracked documentation and tested ZIP entry CRCs, content equality, checksum and under-25-MB size; see release report for actual values.

## NOT performed

No Pi connection, package install/build, dependency solve, application implementation, unit/simulation tests, GUI launch, arm64 execution, service operation, serial/USB/Bluetooth open, esptool probe, settings export, backup/restore, erase/flash, radio reconnection or RF TX. No hardware compatibility/recovery acceptance passed.

**All Firmware Manager hardware behavior: UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.**

Joshua's separately hardware-tested Mesh notification improvement is preserved as an input constraint, not retested or claimed as a Firmware Manager result. Radio r3 worktree was not accessed or changed. No existing T.A.S.K. module source or installed Pi file was modified.

## r2 documentation update

Added the conditionally selected working Heltec first-test plan; updated phase/recovery/questions and client-pin preservation. No Pi commands were executed. No private YAML, keys, channel URLs, firmware binaries or source-archive contents were collected. The Radio archive receipt/hash is outside this task; no verification claim is made for it. Exact image and image SHA256 remain unknown until approved device firmware identification/acquisition. Proposed command snippets are documentation, not executed tests.
