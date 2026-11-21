<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Radio r3.1 adapter specification — proposed interfaces only
Nothing below is claimed installed. Actual callable names/signatures are in API-MATRIX.md and SOURCE-INTERFACE-INDEX.md. This replaces r2's typing sketch rather than layering contradictory signatures over it.

## 1. Confirmed upstream boundary
* Policy: `TxPolicy.evaluate_amateur(req,cfg,radio) -> Decision`; `record_sent` and `frame_done` bookkeeping. Do not add a configurable parallel TxPolicyHook. Direct UV-PRO transport unsupported by existing policy.
* Codec: `KissDecoder.feed(bytes) -> [(port,raw)]`, `kiss_frame(raw,port=0) -> bytes`, `decode_ax25 -> Frame`, `parse_aprs -> AprsPacket` from task_comms.aprs.
* Controller: `AmateurTx(...getters...,clock,on_change)`; `send(kind,*,...,retries=3,path=...) -> (Outgoing|None,Decision)`, `cancel(local_id)`, `tick()`, `on_packet(frame,packet)` from task_aprs.amateur. Radio always passes retries=0 until Q2 resolved; never relies on default path as approval. Controller modifications are separately approved upstream work.
* Receive: `Receiver.handle(channel,raw,mycall="") -> AprsPacket|None`. Preserve third-party APRS-IS provenance, never feed it to RF acknowledgment correlation.
* Claims: `DeviceClaim(key,module,directory=None).acquire()->bool`, `.release()->None`; not a service shutdown API or a Mesh lease.
Exact references and side effects: API-MATRIX.md. No calls to these were executed during review.

## 2. Proposed local Radio contract (not source-code implementation)
| Proposed component / operation | Input -> output | Required semantics |
|---|---|---|
| Identity | kind SIMULATED or future known target + canonical key | B accepts `sim:` only; real MAC/paths rejected, no discovery-open |
| OwnershipView | target -> clear/held/unknown + evidence | unknown never free; cooperative claim != global exclusivity |
| SimulationFactory.create | explicit scenario ID, fake clock, isolated state root -> SimulatedTransport | no network/device options, no hardware registry fallback |
| KnownDeviceRegistry.list_configured | no args -> immutable configured identities | no scan, no inquiry, no automatic connection |
| Link.start / stop | explicit target -> connected epoch / None | B simulation-only, stop idempotent; no writes on start |
| EnablementGuard.enable | typed call + attestation + authenticated context + target/profile/epoch -> opaque permit | memory-only; in tests SIMULATION ONLY; cannot mint physical hardware authority |
| EnablementGuard.authorize_write | permit + frame digest + channel + target + current shared Decision -> one-use WriteTicket | returns ticket (not None); reject stale/revoked/expired/scope mismatch; deny if policy refused |
| EnablementGuard.revoke | reason -> None | increments revocation epoch; closes application write gate synchronously |
| GuardedTransport.send_raw | installed controller's channel:int, raw:bytes -> None or explicit exception | internal wrapper authorizes at LAST write, consumes ticket bound to exact frame/channel/epoch; controller never receives unguarded hardware transport |
| SimulatedTransport | name, connected, has_queue_feedback; connect/close; send_raw(channel,frame); outstanding(channel) | conforms only to fixture Direwolf protocol interface; no real socket; send records SYNTHETIC bytes; outstanding integer is synthetic queue count |
| SimulationPeer.inject_rx | explicit raw frame, channel, time -> receive callback | callback marshalled through serial dispatcher; labels always SIMULATED |
| SimulationPeer.auto_response | enabled=False, deterministic rule -> synthetic response | default off, nonpersistent, test-only; never authorizes own-station automatic RF acks |
| RadioSession.send_message | user request + addressee/text + live permit + explicit path/retries -> local request result | delegates to AmateurTx; typed boundary validation; no automatic work from receiver |
| RadioSession.cancel / kill | local request / no args -> cancellation record | kill revokes before draining, no new write after return, incomplete work not replayable |
| StatusProjection | installed controller event + permit state -> sanitized UI state and comms status card | distinguish sent/submitted, queue-progress, acked; never 'on air' |

These names are intentionally proposed; they are not task-core/task-comms APIs. Their implementation waits for explicit approval.

## 3. Types and identity invariants
Canonical payload = immutable raw AX.25 bytes without KISS escaping/FCS. Reception metadata = channel, simulated/RF/APRS-IS provenance, connection epoch, wall/monotonic receipt times, optional measured metadata. No invented RF RSSI or frequency. Local message ID differs from wire APRS ID; correlation uses peer/local callsign/channel/epoch/freshness. Private message bodies never enter status, notification preview when locked, raw diagnostics, or audit.

Permit scope = session validity + target + profile + connection epoch + SIMULATED_ONLY bit + expiry. Nonserializable permit and ticket; never pickled, stored or restored after restart. KILL increments epoch, cancels scheduled/queued work and invalidates every outstanding ticket. Wire-write critical section and cancellation share serialization. Emergency control cannot be blocked by a worker doing a queue query. Already-submitted TNC bytes cannot be undone by this contract.

## 4. Simulator RF isolation (requirements, not a tested guarantee yet)
Simulator package imports no socket, serial, bleak, Bluetooth APIs, shell/subprocess, real transport factory or device enumerator. It runs only in memory/temporary files and fake clocks. Qt test driver and test harness may have their own libraries, but cannot expose a hardware object to the simulator. Shared codec imports are safe; shared client/service modules that contain network code are not simulator dependencies. No environment-variable-only safety boundary; separate package/build inclusion allow-list plus runtime factory rejection plus test sandbox must all hold.

Block AF_INET/AF_INET6 too: localhost TCP can key a real Direwolf. Deny AF_BLUETOOTH and opening character devices, plus process spawning. AF_UNIX is denied in pure B sim tests too so no real Core/Mesh IPC is reached. Inject fake Core, status, audit and notification stores. If tests of AprsService are separately approved, use a sandbox and inject ALL network factories and isolated roots, never connect defaults. Hardware adapter packages not present/importable in B distribution.

## 5. Explicit omissions
No scan method/declaration; no pairing/trust APIs; no vendor data TX; no audio/PTT access; no general serial adapter; no automatic beacon/forwarding/digipeating or RF ack. Future RFCOMM adapter requires recorded firmware/channel/KISS evidence, explicit ownership authorization, approved shared policy extension and physical test. A user-entered channel/UUID alone is insufficient. All such hardware behavior is **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**.

## 6. Error vocabulary (proposed UI codes, not installed RPC errors)
`simulation-target-required`, `busy-owned`, `busy-unknown`, `identity-denied`, `session-uncertain`, `policy-refused`, `tx-disabled`, `permit-expired`, `permit-revoked`, `epoch-mismatch`, `write-timeout`, `queue-full`, `stale-ack`, `wrong-peer`, `wrong-channel`, `hardware-forbidden`. Retain upstream Decision reasons and CoreError code separately; don't replace them with misleading success.
