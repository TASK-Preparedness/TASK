<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Radio r3.1 simulator and safety test plan
**PLAN ONLY — NOT RUN.** Archive digest/hash checks and static source inspection were performed; the proposed implementation/tests below do not exist yet. Do not describe this matrix as passing. All Milestone B data is synthetic and visibly labelled SIMULATION; pytest/offscreen Qt must never reach a real daemon or device.

## Harness requirements
Use /usr/bin/python3, fake monotonic/wall clocks, deterministic scenario seeds, isolated config/state/runtime directories and injected session/policy/store objects. No global HOME/XDG real-data use. Simulator ships/imports no hardware transport. Fail tests on any socket creation/connect (including localhost TCP and real AF_UNIX), character-device open, serial/BLE/BlueZ import/use or subprocess spawn. Stub notification/audio functions. Qt offscreen host stays outside simulator library's import graph. Static allow-list/package-content inspection complements runtime blockers; environment flags alone are insufficient. Future host sandbox must deny network and device access, without installing/changing Pi services.

## Acceptance matrix
All tests have status **NOT RUN / BLOCKED ON APPROVED IMPLEMENTATION** unless explicitly called a static review result.

| ID | Case / stimulus | Pass criterion | Failure criterion |
|---|---|---|---|
| B01 | Simulator import, connect, send, error, reconnect scenarios | only memory/temp state, zero hardware/network/process calls | any external access or transport fallback |
| B02 | Supply real MAC, tty path, gps path, TCP URI or malicious profile in simulation | rejects before factory/OS call, SIMULATED identity retained | actual address accepted or open attempted |
| B03 | Shared KISS codec vectors C0/DB/all byte values, split frames, repeated FEND | uses shared KissDecoder/kiss_frame, exact vectors roundtrip | duplicate Radio codec or changed bytes |
| B04 | Truncated/invalid escape, oversize frame, non-data commands | reject/drop/count matching installed decoder semantics, no crash/TX | malformed frame transmitted or unbounded memory |
| B05 | Shared AX.25/APRS encode/decode/address/SSID/path/text limits | use fixed synthetic vectors, invalid cases denied | silent truncation/misclassification |
| B06 | Invalid states: send disabled/disconnected/connecting/failed/session unknown/ownership unknown | zero transport writes, explicit refusal reason | UI-only check bypass, write succeeds |
| B07 | Explicit simulated enable with typed callsign mismatch or missing attestation/session | refused; no permit | false authorization |
| B08 | Correct simulated enable | nonserializable SIMULATED_ONLY permit scoped to epoch,target,profile | real-hardware permit minted by fixture |
| B09 | Idle timeout boundary, wall-clock jump, heavy RX | monotonic expiry; RX/retries do not extend user idle deadline | TTL survives or wall time bypass |
| B10 | Disable/session end/profile/device change/link loss/restart | revocation and queue cancellation, fresh approval required | persisted enable flag, unprompted replay |
| B11 | KILL with pending requests/retries/tickets, active worker blocked in queue query | return within declared UI/control budget (target 100 ms in sandbox); zero subsequent writes; separate cancel state | blocking GUI; valid stale ticket; future write after return |
| B12 | KILL races immediately before final write | serialized ticket check/write; no newly authorized writes after revoke | check/use race emits post-kill bytes |
| B13 | Already submitted mock TNC frame when kill occurs | UI says submission cannot be recalled, no guaranteed de-key claim | claims already submitted bytes erased/stopped |
| B14 | Message IDs near rollover and after restart | shared-controller correction prevents live/quarantined wire-ID collisions; local epoch distinct | duplicate ID1, stale ack accepted; expose unchanged installed behavior as regression gap |
| B15 | Correct classic ack/rej from peer for current request | transitions once, pending retries canceled | duplicate terminal event or extra send |
| B16 | Wrong peer/local addressee/channel/epoch, old timestamp, unknown/reused ID ack | no successful correlation/state promotion | stale or spoofed context acknowledged |
| B17 | Duplicate RX/history-sync/reconnect replay | one unread/live announcement, no auto-ack; history marked appropriately | duplicated alert/count or RF response |
| B18 | Synthetic peer ack **injected by test** after user send | ack tracking works without enabling incoming-message auto-ack | conflates peer injection with permission to auto-transmit |
| B19 | Incoming addressed message with simulated TX enabled; default config | 'ack owed' indicator; **zero ack writes** | original r2 auto-ack test survives |
| B20 | Optional simulator peer auto-response explicit fixture ON then reset | deterministic synthetic response only; default OFF each run | persisted option or production RF implementation |
| B21 | Q3/Q4 unanswered, auto-ack/reply-ack requested | unavailable/refused outside test fixture; receive parse gaps documented | new automatic RF policy silently enabled |
| B22 | Shared retry_schedule count0/3/4/invalid | installed output []/[30,90,210]/[30,90,210,330], invalid count rejected | tests pretend installed schedule equals Q2 |
| B23 | Approved future synthetic retry candidate 0/30/60/120/240, ack/rej/disconnect/disable | injected fake clock verifies stop/cancel and max bound, no catch-up burst | production Q2 schedule enabled before approval or second scheduler copy |
| B24 | Default send with explicit retries=0 | one synthetic submission only, final no-ack after installed wait if applicable | installed default retries=3 inherited |
| B25 | AGW-like queue busy/drain/error >30s; KISS-like no feedback | installed submitted/queue-progress/failed semantics, no ON-AIR | queue drain claimed RF proof; deadlock blocks kill |
| B26 | Write failure/timeouts, partial frame, disconnect after submit | fail/cancel, discard incomplete RX, no resend until explicit new request | silent requeue; old frame replay |
| B27 | Backpressure/full bounded work queue | explicit queue-full refusal; no hidden drain after disable | unbounded queue or lost failure state |
| B28 | Ownership contention, alias identities, held Mesh lock, inaccessible proc | fail closed with evidence; Heltec/GPS always denied even when apparently free | free DeviceClaim treated as Mesh or Bluetooth lease |
| B29 | Fake Core restart/new boot_id, event gap, stale session, helper timeout | lock private views, revoke enablement, resync read-only state, no writes | retains old token/permit; old sequence trusted |
| B30 | Service fake restart during TX | interrupted terminal work; no autoplay on recovery | service restart reauthorizes TX |
| B31 | Qt offscreen controls/worker callbacks/close | GUI thread signals, obvious SIMULATION, controls never block; close revokes/cancels | real launcher/hardware side effects, thread race |
| B32 | Event/audit/status/privacy fixtures | no body/token/callsign list in status or logs; history private; schema1 states only | secret preview while locked or invented 'on-air' state |
| B33 | No beacons/forwarding/digipeating/automatic RF acknowledgment | no timers/receiver hooks emit them; bridge remains refusing | any automatic send route |
| B34 | Shared policy UV-PRO-like transport with no Direwolf PTT | current policy refuses bad-transport/no-ptt; no spoofing | false Direwolf name or ptt=True to bypass RF block |
| B35 | Package inspection/import audit | sim build contains no hardware adapters, executable autostart, unit, tile replacement | dormant hardware or service change shipped |

Installed controller safety cases B14/B16 are not assumed to pass. First characterization tests should demonstrate gaps; upstream fixes require explicit implementation approval, then the same tests must pass. New synthetic ID/schedule assertions are acceptance targets, not evidence that installed APIs already have them.

## Mesh preservation regression suite (separate 0.3.2 release)
Mock paplay/Popen and sender. Assert exact argv /usr/bin/paplay + user WAV, DEVNULL descriptors, start_new_session=True, close_fds=True and no shell. Assert suppress-sound=True even when sound setting disabled. Test enabled/disabled sound, quiet mode/hours crossing midnight, muted protocol/conversation, focus lease, duplicate/live/history-sync, locked/unknown privacy, grouped bursts. Missing WAV produces no audio; missing paplay/spawn failure logs but notification continues. Existing implementation does not observe asynchronous paplay exit status or cap overlapping sounds: document rather than promise otherwise. Audio regressions require actual incoming Meshtastic message on hardware later with approved restart only. Current real-hardware behavior was user-verified before this review; not rerun here.

## C packaging acceptance on staging Debian 13 ARM64
Use PACKAGING-AND-ROLLBACK.md matrix: pins/API signatures, missing dependency refusal without installs, no replacements/downgrades/removals/autostart, exact notifier/WAV preservation, clean uninstall, unknown modified-file abort, rollback retaining audio. No tests run against Pi during this phase.

## D physical hardware acceptance — NOT AUTHORIZED
Every step **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**. First record firmware/menu state manually, cached Bluetooth details and actual configuration. Remote SDP and listen-only connection each need separate approval: even connecting is an external radio interaction. No pairing or trust changes. Real transport must show valid KISS/AX.25 frames; silence is inconclusive, not confirmation. No hardware TX until questions answered, shared policy/controller safety fixes accepted, exact target and legal frequency approved, licensed operator present, lowest appropriate power, suitable dummy load first, second station available, power/PTT intervention planned. One explicit frame then observe actual radio and receiver; no promise UI kill de-keys radio. Test loss/reconnect/restart without replay, audio/device independence and receive behavior. Stop on any uncertainty; publish physical evidence with firmware/image versions only after actual tests, never promote simulator results.
