# T.A.S.K. Firmware Manager — Milestone A, revision 2

Research and architecture only • 2026-11-08 (America/New_York, EST)

**UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**

No application code, Debian packages, firmware images, executable flashing scripts or device tests are included. No Pi access, installation, service change, radio configuration, download of firmware binaries or RF transmission was performed. This is a separate local repository, branch `phase-fwmgr`; the Radio r3 worktree was not accessed or modified.

## r2 update

Joshua selected his working Heltec V3 915 MHz as the first physical-test device, conditional on verified backup and safe procedures. No Pi action or flashing is authorized yet. The new first-test plan distinguishes pinned Python client 2.7.11 from the still-unknown radio firmware version; no exact image/hash is invented. Each proposed Pi step requires explicit approval.

## Decision

Feasible in principle as an offline native PySide6 module. **Not approved or ready for implementation yet.** Board variants, installed integration interfaces, pinned image recipes, firmware licensing and first-boot RF safety remain gates. USB detection is not proof of board identity. A successful flash process is not proof of a working radio.

### Read in order

1. [Board feasibility](docs/01-feasibility.md)
2. [Offline tools and image formats](docs/02-offline-tools.md)
3. [Compatibility and roles](docs/03-compatibility.md)
4. [Vault and manifest specification](docs/04-vault.md)
5. [Ownership and coordination](docs/05-ownership.md)
6. [Native UI design](docs/06-ui.md)
7. [Offline packaging](docs/07-packaging.md)
8. [Development and hardware acceptance](docs/08-plan-and-tests.md)
9. [Licensing and redistribution](docs/09-licensing.md)
10. [Rollback and recovery](docs/10-recovery.md)
11. [Source review and open questions](docs/11-source-review-and-questions.md)
12. [Sources and evidence limitations](docs/SOURCES.md)
13. [Heltec V3 first-test plan](docs/12-heltec-v3-first-test.md)
14. [Release validation record](docs/VALIDATION.md)

Source labels such as [S01] resolve in SOURCES.md. Public documentation establishes upstream capabilities only, never hardware acceptance on Joshua's boards. All designs are proposals, not claims of implemented existing T.A.S.K. APIs. Reported Pi facts come from Joshua's t68u/t69u inventory, not new inspection.

**Preservation invariant:** never overwrite the working Mesh 0.3.1 notifier, sound, pre-audio backup, service policies, other modules, configs or data. No autostart, root GUI, global pip, `shell=True`, flashing, RF TX or service operations are authorized by this document.
