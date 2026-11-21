<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Radio r3.1 — installed-source reconciliation
Review date: 2026-11-08 EST. Documentation/source analysis only; no Pi connection, installation, restart, Bluetooth connection, flashing, or RF transmission. No Milestone B code written.

## 1. Evidence and verification
Authoritative input: `task-r3-sources-20261108-112630.tar.gz`, SHA-256
`f479d7713707ede16dd39668487762b3b07f5ad65810f014057430b7a3565d2b` — **MATCH**.
Archive fully read and safely extracted under `/workspace/r3-real/extracted`; every member checked for absolute names and `..`, Python's data filter applied. 632 archive members: 593 regular installed files plus 38 inventory files and one inventory directory. Collection says `None` errors (`inventory/collection-errors.txt:1`); no collection warnings are reported. The earlier missing attachment and unrelated rain-mesh candidate are not evidence and were discarded from `/workspace/r3-sources`.

References beginning `/usr`, `/etc`, `/home/<user>` resolve under the archive's `installed/`, not this box's OS. `inventory/` references resolve at archive root. Line numbers refer to original extracted text, not an earlier repository copy. This ZIP deliberately excludes installed sources, databases, account/config data and WAV files. `API-MATRIX.md` gives callable contracts; `SOURCE-INTERFACE-INDEX.md` records signatures, source locations and reviewed hashes.

Installed package evidence (`inventory/versions.txt:9-19`): task-core 0.3.0, task-core-compat 0.3.0, python3-task-comms 0.3.1, task-aprs 0.1.0, task-mesh 0.3.1, task-launcher 0.3.7. Runtime Core version is **0.2.1**, not Debian package version 0.3.0 (`/usr/share/doc/task-core/MIGRATION.md:34-35`; `/usr/lib/python3/dist-packages/task_core/__init__.py:5`). A probe must not reject this legitimate combination.

### Coverage limits — do not turn omissions into facts
* **No Direwolf configuration file is present in the 593 collected installed files.** This is a completeness gap, not proof no file exists on the Pi. The bundled code, not host filesystem reads, was inspected. Actual configured KISS/AGW ports remain **UNDETERMINED** (details below).
* `inventory/files-task-core-compat.txt:12` lists `/usr/bin/rain-core-admin`, but the file/link itself was not collected. The collector's regular-file list omits it (`inventory/collected-files.txt`). Wrapper target therefore is not confirmed. Preserve compatibility; request `readlink` plus its resolved content, not rerun migration.
* gpsd status and `/etc/default/gpsd` are present; full gpsd.service/gpsd.socket unit definitions and their overrides are absent. Preserve their policy, do not invent unit contents.
* No Debian control files, maintainer scripts or full Python/PySide6 dependency versions were supplied. Runtime imports support dependency names, not invented exact binary versions. Final package-control resolution is a release gate.

## 2. Core and compatibility findings
Core uses JSON lines on AF_UNIX, not a REST server (`/usr/lib/python3/dist-packages/task_core/api.py:3,17-21,213-224`). Protocol v1 UID roles and v2 session roles coexist: v1 `Server._dispatch` uses `Auth.allows(uid, minimum)` (`/usr/lib/python3/dist-packages/task_core/api.py:132-146`, `/usr/lib/python3/dist-packages/task_core/auth.py:14-27`); v2 `V2Handler._dispatch` resolves sessions bound to peer UID (`/usr/lib/python3/dist-packages/task_core/protocol_v2.py:90-104`, `/usr/lib/python3/dist-packages/task_core/sessions.py:205-219`). Radio must use v2 and its own session; no token copied from launcher.

`device.list`, `device.get` and logical `radio.primary` are assignments/discovery, **not physical I/O leases** (`/usr/lib/python3/dist-packages/task_core/devices.py:13,350-418`). Core's udev enumerator does not open nodes (`/usr/lib/python3/dist-packages/task_core/enumerator.py:3,248-270`). It watches tty/net/usb, not a supported Bluetooth KISS registry. `Bus.publish` is in-process (`/usr/lib/python3/dist-packages/task_core/bus.py:32-40,64-91`); there is no public event-publish RPC in `/usr/lib/python3/dist-packages/task_core/protocol_v2.py:20-36`. Capabilities are status with no providers registered by this module (`/usr/lib/python3/dist-packages/task_core/capabilities.py:23-48`), not transport guarantees. There is no GPS-fix RPC in the v2 method table: gpsd remains the position source.

Core manifests are existing `radio`, `mesh`, `gps` IDs, version 0.1.0 definitions, `systemd: []` (`/usr/lib/task-core/modules/radio.yaml:1-14`, `mesh.yaml:1-14`, `gps.yaml:1-14`). Manifest version is not installed package version. Do not replace them to claim Radio r3 implementation or `radio.tx` readiness. Parser validates module ID/filename, known capabilities and logical devices (`/usr/lib/python3/dist-packages/task_core/modules.py:186-232`). Core loads manifests at startup (`/usr/lib/python3/dist-packages/task_core/main.py:99-102`); no hot-register RPC exists.

Migration remains authoritative: `/usr/lib/systemd/system/task-core.service:8-23` conflicts with rain-core, requires `/etc/task/MIGRATED`, runs as rain-core, and creates `/run/rain/core.sock` compatibility link. Existing enabled/running state is evidence (`inventory/core-status.txt:5-6`), not permission to change it. task-core-compat has clean dpkg verification; its uncollected wrapper is a specific coverage gap, not an invented second daemon.

## 3. Actual Direwolf/APRS result
**Configured KISS TCP port: UNDETERMINED. Configured AGW TCP port: UNDETERMINED. No active Direwolf process observed. No listener is positively attributable to Direwolf.**

`inventory/direwolf-process.txt:1-4` has `pgrep -a direwolf`, exit 1, no process. `inventory/listeners.txt:5-49` includes `*:8000` and `127.0.0.1:8001` but omits owning process for those entries. Do not call either Direwolf merely because its number matches a default. No connect/protocol probe was performed. No generated Direwolf conf exists in task-aprs' code: the package explicitly never writes it or starts/stops Direwolf (`/usr/lib/task-aprs/task_aprs/dwconf.py:3-4`, `/usr/lib/task-aprs/task_aprs/config.py:3-7`, `/usr/lib/task-aprs/task_aprs/app.py:3`). Earlier r3's claim 'task-aprs owns Direwolf via generated conf' is withdrawn.

Confirmed **code fallbacks only**: `dwconf.DEFAULT_KISS=8001`, `DEFAULT_AGW=8000`; search order `~/direwolf.conf`, `/etc/direwolf.conf`, `/etc/direwolf/direwolf.conf` (`/usr/lib/task-aprs/task_aprs/dwconf.py:9-13`). `parse(text,path)` reads KISSPORT/AGWPORT (`:69-107`); effective ports default when absent, explicit 0 disables (`:40-46`). `load(paths)` returns the first available config, or an error object still possessing fallback effective ports (`:110-119`). This must not become a claim of observed configuration.

`AprsService.connect()` prefers AGW, falls back to each KISS port (`/usr/lib/task-aprs/task_aprs/service.py:71-92`). Constructor accepts `dw_conf`, factories and temp roots (`:25-50`) but otherwise loads user settings, creates feed/audit objects, and uses real TCP factories. Do not instantiate it as a harmless simulator with defaults. Launcher discovery is broader: checks process/unit `-c`, cwd, home and `/etc` (`/usr/share/task-launcher/task_launcher/services/direwolf.py:124-175`). Its TCP reachability is not protocol identity. Alignment of both config resolvers needs an approved adapter; no new hard-coded ports.

Reuse the actual codec in `task_comms.aprs` (not a second Radio codec): `KissDecoder.feed`, `kiss_frame`, AX.25 parse/encode, APRS message/ack helpers. `task_aprs.kiss.KissClient` is TCP-only and loopback guarded; it is **not** RFCOMM (`/usr/lib/task-aprs/task_aprs/kiss.py:9-27,42-58`). `AmateurTx` already supplies IDs, delivery states, retries and ack matching (`/usr/lib/task-aprs/task_aprs/amateur.py:64-77,126-150,180-250`), and `Receiver.handle` supplies packet/station handling (`/usr/lib/task-aprs/task_aprs/rx.py:45-89`). Reuse via thin adapters, not parallel packet engines.

### Real incompatibilities in existing APRS reuse
1. Shared `TxPolicy.evaluate_amateur` only allows `direwolf-agw`/`direwolf-kiss` and requires `ptt_configured` (`/usr/lib/python3/dist-packages/task_comms/txpolicy.py:169-204`); direct UV-PRO RFCOMM cannot honestly satisfy that contract. **Approved upstream policy/transport extension required before any physical Radio TX.** Never lie about transport name or PTT.
2. `AmateurTx._evaluate` sets `user_initiated=True` for all its calls, including `tick` retries (`/usr/lib/task-aprs/task_aprs/amateur.py:88-98,209-212`). Programmatic caller cannot rely on that field to prove actual approval. Radio must require an explicit user request plus live enablement at the last write and default `retries=0`.
3. Shared retry schedule is cumulative 30,90,210 seconds for count=3; count=4 adds 330, not proposed 30,60,120,240 (`/usr/lib/python3/dist-packages/task_comms/txpolicy.py:52-53,281-289`). `AmateurTx.send` defaults retries=3 and WIDE1-1,WIDE2-1 (`/usr/lib/task-aprs/task_aprs/amateur.py:126-131`). Q2 is not approved: neither silently inherit defaults nor replace the shared scheduler locally.
4. Message sequence restarts per controller and wraps with potential duplicate '1' (`/usr/lib/task-aprs/task_aprs/amateur.py:72-77`). Ack matching checks peer+ID+local addressee but lacks epoch, freshness and channel check (`:227-250`). Stale/reused IDs and wrong-channel acks need an approved controller correction; don't assert existing guarantees.
5. `cancel` cancels controller work, not bytes already handed to TNC (`/usr/lib/task-aprs/task_aprs/amateur.py:152-178`). AGW queue count is only queue feedback (`/usr/lib/task-aprs/task_aprs/agw.py:9-11,148-153`); KISS has none (`/usr/lib/task-aprs/task_aprs/kiss.py:3-4`). Emergency kill cannot retract queued RF or guarantee de-keying.
6. TX settings are persisted by existing config helpers (`/usr/lib/task-aprs/task_aprs/config.py:65-84`). Captured amateur TX is false and callsign/attestation empty (`/home/<user>/.config/task-aprs/amateur.toml:2-6`). Captured **GMRS TX and auto-reply switches are true**, with empty attestation (`/home/<user>/.config/task-aprs/gmrs.toml:2-7`); that is not authorization and policy still requires attestation/equipment/session (`/usr/lib/python3/dist-packages/task_comms/txpolicy.py:207-260`). Do not copy or change these preferences. Radio's enablement must be memory-only and independent of saved switches.
7. Service callbacks can arrive from reader threads (`/usr/lib/task-aprs/task_aprs/agw.py:96-116`, `/usr/lib/task-aprs/task_aprs/kiss.py:48-65`); Qt adapters marshal signals and serialize controller calls. Partial AGW failures can leave resources needing explicit cleanup; tests must cover constructor/connect and close failure paths.

GMRS remains separate: abstract `GmrsDriver`, empty registry, simulation implementation only (`/usr/lib/task-aprs/task_aprs/gmrs/driver.py:40-73`, `gmrs/simulated.py:12-52`; `/usr/share/doc/task-aprs/GMRS-HARDWARE-RESEARCH.md:3-5,24-38`). No UV-PRO GMRS assumption, no external-modem GMRS route.

## 4. Communications and ownership conflicts
`task_comms` is process-local helpers, **not a central broker** (`/usr/lib/python3/dist-packages/task_comms/__init__.py:3-6`). `DeviceClaim` is advisory flock under task/locks using sanitized caller key (`/usr/lib/python3/dist-packages/task_comms/ownership.py:51-93`); `holders` has limited visibility (`:3-6,18-48`). Mesh instead uses task/mesh-devices/<resolved tty>.lock (`/usr/lib/task-mesh/task_mesh/hub/locks.py:106-117`). Thus a free DeviceClaim does not prove Mesh is free. Radio avoids the Heltec altogether, not by acquiring a competing lock. Bluetooth SPP occupancy is not solved by file-descriptor serial checks; a stable `bt:<uppercase-MAC>` claim only coordinates cooperative Radio clients. Unknown occupancy fails closed.

`SessionGate.unlocked` checks a locally held token and local idle clock, and `CoreClient.has_role` uses cached role, not a fresh server decision (`/usr/lib/python3/dist-packages/task_comms/auth.py:23-47`; `/usr/lib/python3/dist-packages/task_comms/core.py:90-91`). A future live adapter must validate session.whoami at enable/submission and conservatively expire its session-validity lease on failure; a cached role alone cannot prove current server authorization. Cross-process invalidation latency must be bounded and disclosed, not claimed instantaneous. B uses only synthetic sessions.

`CoreClient.call` allows read/session methods but forbids assignments; its generic call closes after first response, so `events.subscribe` is **not a usable streaming consumer through this helper** (`/usr/lib/python3/dist-packages/task_comms/core.py:14-16,50-75`). Core server has real stream support (`/usr/lib/python3/dist-packages/task_core/api.py:239-262`, `protocol_v2.py:171-180`); a future bounded read-only stream adapter needs approval. Prefer conservative health/device polling initially; restart/session uncertainty revokes TX. `EventLog.log` is local redacted JSONL, not shared event delivery (`/usr/lib/python3/dist-packages/task_comms/events.py:15-38`). `Bridge.forward` always refuses (`/usr/lib/python3/dist-packages/task_comms/bridge.py:3-16`). Preserve refusal, no forwarding.

`NotificationStore` supplies source+ID deduplication and unread state; desktop formatter is Mesh-specific (`/usr/lib/python3/dist-packages/task_comms/notifications.py:90-162,254-277`). Radio may reuse storage but must propose a separate Radio presentation adapter, no 'Mesh' identity or sound reuse by accident. StatusWriter accepts a limited schema (`/usr/lib/python3/dist-packages/task_comms/status.py:18-56`), not arbitrary ON-AIR or TX-enabled states. Use rx-only/queued/error plus sanitized indicators; connected/tx-capable is not authorization.

## 5. Launcher conflict discovered
The current tile **already exists**: `/usr/share/task-launcher/apps.d/030-radio.toml:3-20`, id `task.radio`, builtin radio + exec `/usr/bin/task-aprs`. Activation prefers the external command if installed (`/usr/share/task-launcher/task_launcher/ui/main_window.py:402-445`). Do not overwrite it or create a duplicate `task.radio`.

Launcher manifests use TOML registry discovery (`/usr/share/task-launcher/task_launcher/registry/discovery.py:37-82`) and `parse_doc` (`/usr/share/task-launcher/task_launcher/registry/manifest.py:238-333`); Core YAML manifests are a separate registry. Unknown `[panel]` is rejected (`:28-33,241-243`); generic plugin-panel loading is not implemented. Existing embedded view list is **medical only** (`/usr/share/task-launcher/task_launcher/ui/main_window.py:34-35,425-426`). A reusable Qt Radio widget can be designed for later embedding, but automatic native launcher integration requires a separate approved launcher change. External app/test harness first; tile ID/final placement still needs approval. Historical MODULE-API.md prose is not authority over the installed parser.

## 6. Contradictions resolved in r3.1
| Earlier assertion | Correction |
|---|---|
| remove scanning but DeviceManager.start_scan remains | Delete discovery method; explicit preconfigured identity only; no inquiry, scan, pairing or trust action |
| enabled TX automatically emits ack in B test | default auto-ack **off**; incoming message shows ack owed; synthetic peer ack injection is independent; optional simulator auto-response explicitly test-only/off |
| token check returns None yet writer expects GuardTicket | proposed authorize_write returns a single-use ticket bound to epoch, frame, target; recheck at final write |
| new Radio codec/test oracle | no duplicate codec, even as an oracle; test shared codec with fixed synthetic vectors |
| retries always resume after reconnect | cancel/fail pending work on disconnect; never replay; fresh approval, no catch-up burst |
| user assertion/UUID sufficient for RF TX | neither permits hardware TX; requires physical verification plus policy integration and explicit authorization |
| persisted base36 IDs already supported | installed decimal in-memory IDs; approved collision/epoch changes required; simulator tests expose gap |
| shared policy directly supports UV-PRO | it currently rejects it; upstream extension required |
| task-aprs generates/owns Direwolf | false; it only connects to an already running daemon |
| Core version must equal Debian version | runtime 0.2.1 is expected with package 0.3.0 |
| any new tile is conflict-free | task.radio already belongs to launcher; no overwrite |
| Mesh uses same DeviceClaim namespace | false, separate mesh-devices resolved-tty locks |
| 'KILL' guarantees RF stops | only future writes canceled; operator power/PTT intervention required for external queued transmission |
| provisional sound licensing/recipe missing | upstream credit and exact recipe now documented in MESH-AUDIO-PRESERVATION.md |

## 7. Package verification and ownership evidence
All 10 supplied `verify-*.txt` reports were inspected. Only `inventory/verify-task-mesh.txt:4` reports a digest difference: `/usr/lib/task-mesh/task_mesh/hub/notifier.py`. Core, compat, comms, aprs, launcher, console, maps, resources, sdr reports contain no discrepancy (each command/exit record followed by no discrepancy, exit 0). Exit 0 alone is not a clean report: Mesh proves why output must be parsed. Untracked backup/WAV and private configs are outside dpkg's ordinary packaged digest check. No claim that the whole filesystem is unmodified.

`inventory/serial-devices.txt:5-6`, `serial-ownership.txt:4-6`, `mesh-status.txt:13-17` establish Heltec ttyUSB0 held by Mesh. GPS path is exactly the archive spelling with underscores around the product segments (`/etc/default/gpsd:3`, `inventory/gps-status.txt:5-15`), not the earlier prose spelling. GPS service is **active but disabled**, socket-triggered (`gps-status.txt:5-9`); Mesh **active but disabled** (`mesh-status.txt:5-6`). Core active/enabled. No service policy changes.

### Additional manifest and documentation review
All seven installed Core manifests were inspected. `/usr/lib/task-core/modules/sdr.yaml:1-14` requires radio.rx/sdr.primary; `weather.yaml:1-14` requires weather.products with no logical hardware; `medical.yaml:1-14` has reference permission and no device; `system.yaml:1-14` no required capabilities/device. None starts a service. Preserve all seven unchanged; Radio is not a reason to touch unrelated modules.

Installed comms docs were reviewed: `/usr/share/doc/python3-task-comms/COMMS-STATUS.md:3-18` specifies schema1 privacy/heartbeat/no-ON-AIR; `/usr/share/doc/python3-task-comms/NOTIFICATIONS.md:5-6` contains stale packaging-stage prose, while its `:30-42` documents actual 0.3.1 additions. Installed code/version is authoritative over stale 'not packaged' text. Launcher MODULE-API design proposal likewise is not an implemented generic plugin contract (`/usr/share/doc/task-launcher/docs/MODULE-API.md:16-18,48-54`).

## 8. Deliverables and verdict
1. This report, source verification and line references.
2. API-MATRIX.md + SOURCE-INTERFACE-INDEX.md.
3. OWNERSHIP-MATRIX.md.
4. RISKS-AND-OPEN-QUESTIONS.md (all remaining blockers).
5. ARCHITECTURE.md + ADAPTER-API-SPEC.md (corrected, proposed APIs explicitly labelled).
6. TEST-PLAN.md (acceptance criteria, not claims of executed tests).
7. MILESTONE-B-SEQUENCE.md (gated implementation).
8. PACKAGING-AND-ROLLBACK.md (Debian 13 ARM64, no autostart).
9. MESH-AUDIO-PRESERVATION.md (verified hashes, exact recipe, credit).
10. **CONDITIONAL GO** for offline simulator-only Milestone B development **after Joshua explicitly authorizes coding**; source analysis and docs are complete within collected evidence, not a hardware/API readiness certification. **NO-GO now for physical integration, installation or RF.** Configured Direwolf ports, UV-PRO protocol/channel/firmware, shared TX-policy extension, controller safety changes and Q1–Q7 remain gates. No code begins on the strength of this verdict.

Radio remains independent of Firmware Manager; no changes to `/workspace/task-firmware-wt`.
