# 9. Free/open-source and firmware redistribution review

Research guidance, not legal certification. **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**. No third-party firmware binaries or proprietary images are included in this release. A project-level license does not settle every linked library, bootloader, asset or binary blob.

## Component-specific conclusions

| Component | Verified evidence | Packaging decision |
|---|---|---|
| New T.A.S.K. module | Project requirement GPL-3.0-or-later [U70 and standing brief] | Keep new application free/open-source under project policy. Complete notice/header and dependency compatibility audit before code release. Do not relabel upstream components. |
| Meshtastic firmware | Repository includes GNU GPL version 3 text [S10] | Redistribution is possible subject to its actual notices and GPL conditions, including corresponding source/build scripts and third-party dependencies. Preserve exact source commit, patches, build inputs and licenses; don't infer “or later” for every upstream file from the presence of a GPL text alone. |
| MeshCore core/open firmware examples | v1.18.0 `license.txt` MIT, copyright Scott Powell / rippleradios.com [S17]; README confirms MIT [S12] | MIT permits redistribution with copyright/permission notice and disclaimer retained; exact compiled dependencies still need separate review. |
| MeshCore standalone T-Deck/Ultra and native mobile apps | FAQ explicitly excepts these from open source [S13] | Free to download/use is not a redistribution grant. Default FOSS vault must exclude closed standalone firmware unless a separate policy is approved and actual rights established; no automatic inclusion of a proprietary blob. Open `LilyGo_TDeck` companion/repeater release targets are a different scope. |
| esptool upstream 4.7.0 | GPL version 2 text [S22]; Debian build is DFSG-repacked [S25] | Prefer unchanged Debian package with copyright and corresponding source. Do not assume right to bundle upstream stub binaries from project name; audit exact Debian source/repack. Separate-process invocation avoids copying tool code into the app but does not remove redistribution obligations. |
| Adafruit nRF52 nrfutil | BSD-3-clause-style Nordic notice and retained conditions [S23] | Future optional adapter only; preserve source/binary notices and no-endorsement clause. Audit dependency licenses and compatibility before adding. Not part of first ESP package. |
| ESP-IDF, software bootloaders, ROM | Espressif original source Apache-2.0 plus per-component licenses; source headers prevail [S24] | Record actual bootloader/toolchain/component versions for each image. ROM already in chip is distinct from a redistributed software bootloader image. Do not flash ROM, burn eFuses or replace a bootloader generically. |
| Arduino-ESP32 | Repository supplies LGPL-2.1 license text [S24] | Exact linked core/dependencies and notices need audit; a combined firmware binary may carry source/relinking obligations. No blanket assertion all vendor blobs are open-source. |
| PySide6/Debian dependencies | Debian package availability [S25–S28] is NOT a license audit | Preserve Debian copyright/source artifacts, inspect Qt/PySide and all dependency terms in the build before redistribution. Avoid vendoring an unrelated Qt build. |
| Existing Mesh sound | User reports freedesktop `alarm-clock-elapsed.oga` derivative, amplified 26 dB + 0.95 limiter [U69] | Preserve installed bytes, but no redistribution rights are inferred from its filename. Obtain original package/source/license plus modification record in separate canonical Mesh work. Firmware Manager ships no copy. |

## Distributable firmware-pack approval checklist

1. Exact artifact, board/role/release commit and SHA256, no untraceable binary imports labeled official.
2. Source for the precise binary, submodules, build configuration/toolchain/library locks, patches and flashing/install recipe; preserve upstream copyrights and notices. A moving branch URL alone is not adequate corresponding-source evidence.
3. Firmware/bootloader/partition/filesystem/OTA assets classified separately. Include component inventory/SBOM and license expressions plus actual notice texts. Audit precompiled Wi-Fi/BLE/SDK blobs individually; if source or redistribution permission is unknown, the pack's **FOSS/redistribution status is pending/blocked**, not approved by analogy.
4. Satisfy GPL object/source distribution using an appropriate valid method [S10]; proposed offline packs accompany corresponding source on the same media for field completeness. If source packs exceed 25 MB, split compliant source delivery, do not drop source or claim a link alone always satisfies obligations.
5. Preserve MIT/BSD/Apache notices and review LGPL relinking/source terms as applicable. No license grants trademark endorsement rights. No app branding reuse based merely on repository access.
6. Separate provenance/integrity verification from a legal review: a correct hash cannot supply a missing license. Bare local user imports can remain private quarantine, not public redistributable catalog entries.

## Permission and offline behavior

No firmware/library/tool downloads happen automatically. An online acquisition requires permission for the named source/version/board/role and a review of source/licensing; importing from USB does not change licensing duties. Firmware Manager does not bypass proprietary unlocks, buy keys or require paid features. The unidentified Android screenshot cannot establish a reusable tool license or native API; request name/screenshot if functional parity matters.

An unconditional “all bundled binaries are FOSS” claim is currently unjustified. The host design can be GPL and fully offline while a particular upstream firmware pack remains blocked by unknown component/blob provenance. Report that conflict explicitly to Joshua rather than silently weakening the free/open-source requirement.
