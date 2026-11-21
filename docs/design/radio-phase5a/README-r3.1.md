<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# T.A.S.K. Phase 5A — Milestone A r3.1 source reconciliation
Documentation-only review of the actual installed Pi source archive. Start with SOURCE-RECONCILIATION-r3.1.md.

## Deliverable map
1. Source reconciliation and exact references: SOURCE-RECONCILIATION-r3.1.md; SOURCE-INTERFACE-INDEX.md; DIAGNOSTIC-EVIDENCE.md.
2. Actual API/parameter/return/compatibility matrix: API-MATRIX.md.
3. Device/service ownership: OWNERSHIP-MATRIX.md.
4. Remaining incompatibilities/blockers + seven original questions: RISKS-AND-OPEN-QUESTIONS.md.
5. Corrected architecture and proposed adapter contract: ARCHITECTURE.md; ADAPTER-API-SPEC.md.
6. Simulator/safety and acceptance tests: TEST-PLAN.md (plans NOT RUN).
7. Gated B implementation sequence: MILESTONE-B-SEQUENCE.md.
8. Debian 13 ARM64 dependencies/install/rollback: PACKAGING-AND-ROLLBACK.md; DEPENDENCY-ASSESSMENT.md.
9. Authoritative Mesh audio bytes/recipe/license/0.3.2: MESH-AUDIO-PRESERVATION.md.
10. Verdict: CONDITIONAL GO only for explicitly approved simulator coding; NO-GO now for hardware/install/RF. INTEGRATION-REQUESTS.md and CHANGES-r3.1.md summarize next actions.

Archive SHA-256 verified MATCH: f479d7713707ede16dd39668487762b3b07f5ad65810f014057430b7a3565d2b. 593 installed files, 632 archive members. Only notifier.py listed modified in package verification. Actual configured Direwolf ports are UNDETERMINED: no config collected, no process, listener ownership absent. Do not use 8000/8001 defaults as observed settings.

The ZIP contains only current r3.1 documentation and text provenance/checksum records. No code, installer, private source archive/config/database or WAV. Historical r2/r3 documents are preserved in git with superseded notices but excluded from this release ZIP. Read RELEASE-METADATA.txt for commit/checksum scope; SHA256SUMS lists document content hashes.
