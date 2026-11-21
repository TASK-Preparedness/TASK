<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Radio r3.1 blockers, risks and original transmit-policy questions
## Verdict
**CONDITIONAL GO**: simulator-only Milestone B implementation can begin after explicit coding approval, under structural no-hardware isolation. **NO-GO**: physical integration, installation, Bluetooth connection and RF now. No code started. Approval of this document is not approval to transmit.

## Remaining blockers / incompatibilities (complete review list)
| ID | Gap | Consequence / closure |
|---|---|---|
| G1 | Explicit implementation approval not given | All B coding waits; this review is docs only |
| G2 | UV-PRO firmware, actual SDP channel/protocol/KISS mode, RF behavior unknown | **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**; no SPP=KISS assumption, no scan/connect/trust change now |
| G3 | No Direwolf config collected; process absent; 8000/8001 listeners unattributed | configured ports UNDETERMINED; collect candidate config/actual command-line evidence read-only, never probe sockets or assume defaults |
| G4 | Shared policy only accepts Direwolf transports and PTT facts | upstream approved transport/policy extension before direct UV-PRO, no fake facts or second policy engine |
| G5 | Controller retries default3/cumulative schedule differs from Q2 | force retries=0 for B; shared scheduler amendment only after answer and approval |
| G6 | Existing IDs reset/rollover; ack matching lacks freshness/channel/epoch | characterize failures; approved shared controller fixes required for reliable real integration |
| G7 | Controller always marks internal request user_initiated, tick can resend | guard final write with current enablement/authorization; no implicit approval from boolean |
| G8 | Core assignment != lease; comms flock != Mesh namespace; Bluetooth occupancy not globally discoverable | never open Heltec/GPS; future BT canonical claim plus independent occupancy evidence, unknown fails closed |
| G9 | CoreClient is blocking one-shot, not streaming; cached local role/token does not prove current server session; no event publish/GPS fix RPC | use fakes in B; future bounded read-only adapter or polling; gpsd source separately, no invented API |
| G10 | AprsService constructor has real factories, feeds/status/audit and saved TX config | no default instantiation in sim; explicit safe dependencies/temp roots; avoid competing production feed/status |
| G11 | Existing amateur/GMRS config persists switches; captured GMRS TX/auto-reply true | not authorization; Radio never inherits them; leave Pi configs untouched, own memory permit only |
| G12 | KILL cannot withdraw TNC queue or de-key a radio | only cancel future application writes; physical power/PTT fallback required; never claim RF shutdown proof |
| G13 | Callback/queue-query blocking and cancellation races | serialized final gate, thread-marshalled Qt callbacks, bounded waits, stress tests before release |
| G14 | task.radio already launcher-owned; no generic plugin/Radio embed | no overwrite/new duplicate tile; final tile ID/placement approval and separate launcher change for embed |
| G15 | Shared desktop formatter Mesh-specific, status schema fixed | storage reuse OK; new Radio presentation adapter, privacy controls and renderer compatibility review |
| G16 | compat rain-core-admin content/link uncollected; gpsd complete units absent | preserve migration/compat and service policies; request specific missing read-only evidence |
| G17 | Missing exact Qt/Python package metadata and full Mesh control/scripts | dependency plan not final .deb; collect metadata and rehearse offline install/rollback on staging |
| G18 | Sound asset original Pi OGA/FFmpeg version absent | author/ShareAlike attribution resolved; no independent byte reconstruction claim; preserve verified WAV and collect provenance before regenerated distribution |
| G19 | New tests/planned code not implemented/executed | this review cannot certify stability/performance/RF; report actual results later, don't label plans passed |
| G20 | All seven policy questions still unanswered; Q6 packaging and Q7 test hardware included | no automatic acks/reply-acks/retries/beacons/physical TX; exact questions below |

No unresolved license author guess remains: upstream CREDITS identifies Tim/corsica_s and CC-BY-SA; Debian per-file metadata identifies 3.0. Obligations and version nuance are in MESH-AUDIO-PRESERVATION.md. New code/source integration into canonical Mesh remains separately approved work.

## Seven transmit-policy questions (reproduced from r3 §7, originally Oct 30)
1. **TX persistence/timeout:** TX enablement is never persisted (off at every start, link loss, device/profile change and KILL) and expires after **60 minutes idle** (adjustable up to 8 h). OK?
2. **Retries/path:** message retries at **t=0, +30, +60, +120, +240 s** (5 transmissions max, then timed-out; one manual re-try round allowed), default path **`WIDE1-1,WIDE2-1`** (choices: none / WIDE1-1 / WIDE1-1,WIDE2-1). OK?
3. **Auto-ack:** should task-radio automatically ack APRS messages addressed to your callsign-SSID while TX is enabled (still subject to txpolicy), or ask each time?
4. **Reply-acks:** should it send APRS 1.1 reply-acks (`{MM}AA`) or only classic acks?
5. **Beaconing in Milestone B:** **r3 default: none** (no position, status or object beacons, per your rule 7). Do you want any beaconing later, and in which milestone?
6. **Simulator packaging:** ship the simulator as a separate `python3-task-radio-sim` package (not a runtime dependency), or keep it source/test-only?
7. **Milestone D:** which callsign/SSID should be used, is a second station available to receive and ack, and is a dummy load available for the TX tests?

Q2 times are offsets from first submission, not intervals between attempts; clarify in approval. Existing shared code is not equivalent. Until answers and approved changes, retries=0, auto-ack/reply-ack off, beaconing absent. Synthetic peer acknowledgments in tests are not approval for automatic RF responses.

## Next safe evidence requests (not commands executed in this review)
No need to recollect all 593 files. Provide these **read-only outputs**, inspecting/redacting private material before sharing:
* `readlink /usr/bin/rain-core-admin`, `readlink -f /usr/bin/rain-core-admin`, then contents of the resolved regular file. No execution of the CLI/migration tool.
* `dpkg-query -s task-mesh task-core task-core-compat python3-task-comms task-aprs task-launcher`, and `dpkg-query -W python3 python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets` for Depends/versions. No apt install/update.
* Read existence/metadata and relevant nonsecret directives for `~/direwolf.conf`, `/etc/direwolf.conf`, `/etc/direwolf/direwolf.conf`, any operator-known custom path. Share KISSPORT/AGWPORT, PTT/ADEVICE/channel directives after private review; redact IGLOGIN passcode/callsign as desired. Do not treat missing archive files as missing Pi files.
* `pgrep -a direwolf`, full `ss -ltnp` observations, and `systemctl cat gpsd.service gpsd.socket` / any known Direwolf units (system or user) read-only. Do not start missing services or protocol-probe ambiguous ports.
* `bluetoothctl info XX:XX:XX:XX:XX:XX (redacted)`, `rfcomm -a` local cached state only, if a refresh is requested. Manually look at firmware/KISS setting; do not toggle.
* Upstream source OGA `sha256sum /usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga`, installed FFmpeg version and sound-theme copyright for future distribution provenance, if desired. Do not rerun FFmpeg over the custom WAV.

Not read-only-local and **not authorized here**: remote `sdptool browse`, RFCOMM open/listen, pairing/trust or menu changes, Bluetooth scanning, real service restarts, PTT, transmit, firmware actions. A later controlled SDP discovery can establish a channel but not prove KISS. No request for credentials/private accounts is needed.
