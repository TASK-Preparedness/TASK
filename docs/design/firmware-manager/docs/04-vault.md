# 4. Offline firmware vault and manifest contract

Proposed specification, not implemented. **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**. Firmware layout requirements derive from [S06–S09,S13–S21]; paths and schema below are new design choices, not existing T.A.S.K. APIs.

## Storage layout

Default single-user proposal (confirm before implementing):

```text
~/.local/share/task-firmware/
  vault/
    objects/sha256/<digest>                 immutable firmware/data object bytes
    manifests/<family>/<board>/<release>/<role>/<manifest-digest>.json
    registry/<registry-version>/boards.json
    recipes/<recipe-version>/              reviewed declarative recipes, not imported programs
    licenses/<component>/<version>/         exact notices and license texts
    sources/<family>/<release>/             source + build inputs / compliance records
    recovery/<board>/<release>/             offline instructions, diagrams and known-good references
  quarantine/<import-id>/                  non-eligible imports awaiting verification
~/.local/state/task-firmware/
  transactions/<transaction-id>/           durable state journal + redacted logs
  backups/<device-id>/<timestamp>/         private device settings/readbacks; NOT public firmware
~/.config/task-firmware/
  preferences.json                         local non-secret preferences, no persisted flash authorization
```

Backups/state directories mode 0700; settings/readbacks mode 0600. Use stable private device IDs; do not put MACs, keys or personal positions in exported reports without permission. No `/library`, Kiwix, ZIM, MBTiles, radio config or existing Mesh data location is reused. A future shared system vault is opt-in and needs its own permissions review; no root GUI.

## Manifest schema v1 (normative draft field table)

This is the proposed JSON contract, not a validated implementation or a ready firmware catalog. Every field is required unless labeled optional. Null/unknown required compatibility fields make the artifact **ineligible**. Unknown schema versions fail closed; no invented sample checksums or executable recipes are included.

| Field / type | Meaning and validation |
|---|---|
| `schema_version`: integer | Exactly 1 for this proposed contract. |
| `artifact_id`: string | Stable catalog identity; never execute or interpret as a path. |
| `family`: enum | `meshtastic` or `meshcore`; other families require registry extension. |
| `version`: string; `release_tag`: string; `source_commit`: string | Human firmware version, immutable upstream tag association and full commit. Do not assume version strings alone encode compatibility. |
| `board_id`: string; `board_revisions`: array | Registry reference and explicitly accepted physical revisions. Empty/wildcard not eligible. |
| `mcu`: enum; `chip_revision_range`: object | `esp32` or `esp32s3` initially, min/max silicon constraints. Future MCU adapters separate. |
| `radio_chip`: string; `rf_band_mhz`: object | Exact RF chip and hardware frequency range; “915 MHz” label alone insufficient. |
| `role`: enum | `meshtastic-application`, `companion-ble`, `companion-usb`, `repeater`, `room-server`. Do not conflate families. |
| `image_kind`: enum | `factory`, `application-update`, `merged`, or a separately reviewed future format. Extension alone insufficient. |
| `files`: array | For each object: basename, size_bytes (positive integer), sha256 (64 lowercase hex), content-addressed object reference, media type, purpose. Reject absolute/parent traversal/symlink paths. |
| `source_url`: HTTPS string; `release_url`: HTTPS string | Exact original artifact and upstream release. Preserve publisher and retrieval metadata; URLs are provenance, not runtime requirements. Local imports still need provenance or remain quarantined. |
| `license`: object | SPDX expression where verified, notices references, component inventory/SBOM reference, redistribution status `approved`/`pending`/`blocked`, reviewer and evidence. Unknown rights cannot enter distributable catalog. |
| `corresponding_source`: object | Source URLs/commit, local archive hashes, build instructions/dependency locks, patches, and compliance method. Required for eligible distributed packs when obligations apply. |
| `flash_requirements`: object | Exact tool ID and qualified versions, explicit chip selection, required flash capacity, layout/partition ID, mode/frequency constraints, boot entry recipe ID, permitted pre/post reset policy. |
| `segments`: array | Object reference + validated offset and length, erase-sector effects, semantic purpose. Reject overlap, overflow, out-of-flash ranges and mismatch to audited partition recipe. All values are release-specific. |
| `erase_policy`: object | Fresh/update/family-switch constraints; exact wipe ranges; loss categories; typed destructive consent required. No implicit erase escalation on retry. |
| `compatible_from`: array | Exact source family/layout/version conditions for non-destructive update. Unknown source state means no update path; do not silently upgrade to erase. |
| `backup_support`: object | Adapter ID/version, known included/omitted data, restore constraints, secret classification, tested coverage. `unknown` means no assurance. |
| `supported_roles`: array | Explicit accepted roles for this board/release; chosen `role` must be a member. Other role images need their own manifests. |
| `recovery_notes`: object | Local document refs + hashes, exact board button guidance, fallback manifest refs, known limitations and do-not-proceed conditions. Must work offline. |
| `verification`: object | Upstream digest/signature evidence or absence, trusted manifest signature/key identity if available, local reviewer, test state, report refs. Local SHA256 alone never becomes publisher authentication. |
| `rf_boot_policy`: object | Known startup/adverts/forwarding behavior, verified containment/boot inhibition requirement, human authorization scope. Unknown => no application boot in production workflow. |

Registry is separate from images: board name, revision, chip, RF chip/band, flash/PMU/peripheral constraints, USB runtime/boot descriptors, VID/PID candidates, expected serial/topology transitions, identity confidence, photo/manual confirmation requirements and recovery references. USB aliases are many-to-one and are never sufficient authority to flash [S19–S21].

## Import from USB / local storage

1. User selects files/folder; no media autorun, automatic downloads or automatic import-to-flash.
2. Read source media without modifying it; copy only selected bounded content into staging. Reject archive bombs, excessive nesting, device nodes, symlinks, external references and traversal paths. Never execute an imported script or shell fragment.
3. Hash original bytes; compare independently trusted publisher hashes/signatures if supplied. A manifest arriving beside a binary is not automatically trusted. Record provenance as verified/unverified, not “official” merely from a filename.
4. Validate schema, exact board/role/chip, component inventory, segment map, license and recovery docs; inspection of image header is supplementary [S21]. Unknown bare `.bin` can be kept in quarantine but cannot be flashed.
5. Show proposed catalog entry, disk usage, trust and limitations; user approves import. Atomic content-addressed commit to vault; do not replace existing version in place. Rehash before every use. Keep old approved images.
6. Flashing is a later separate action requiring maintenance + identity + destructive consent. Imported metadata cannot grant authorization or launch programs.

Optional “Acquire online” is a manually initiated pre-trip workflow: show named upstream URL, version, board, role, bytes and license before any fetch; user approves that fetch; store full bundle/tool dependencies/source/recovery docs for later offline use. No check-on-start, update daemon, telemetry, map upload or background internet calls. Permission to fetch is never permission to flash. Not performed in Milestone A.

## Integrity and space

SHA256 verifies unchanged bytes, not board identity or publisher authenticity [S21]. Store original upstream bytes immutable, never silently rewrite headers. Hash the finalized flash plan and all component bytes immediately before acquiring the write phase; use stable handles/private staging to prevent a USB-media replacement/TOCTOU race. Validate post-write using tool verification/readback where supported and account for documented header normalization [S19]. Keep verification outcomes distinct from device health.

Firmware/source/tool packs can exceed the 25 MB delivery limit; distribute separately versioned chunks under 25 MB each with a complete signed/digested index, exact dependency closure, and no field-time internet resolution. Do not omit legally required sources to meet the cap.
