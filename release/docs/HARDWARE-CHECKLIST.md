# Hardware validation checklist (all items: UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST)

Only after Joshua authorizes installation. Record date, result and notes per line.

## task-core migration
- [ ] `task-core-migrate --dry-run` lists the expected steps; no files change (`sha256sum` of /etc/rain before/after)
- [ ] migration finishes; `task-core-admin status` shows the same devices and assignments as `rain-core-admin` before
- [ ] reboot: task-core starts, rain-core stays disabled
- [ ] `--rollback` brings rain-core back with the original files

## Launcher 0.3.0 / maps 0.1.1
- [ ] launcher opens on the 7" touchscreen; tiles for APRS, SDR, Mesh, Maps appear; saved order kept
- [ ] maps: offline region still renders; online layer loads only with network; cache limit honoured
- [ ] maps: APRS overlay shows stations received on air

## task-mesh 0.2.0
- [ ] upgrade from rain-mesh 0.1.0 keeps messages/nodes; sending a text to a second node works

## task-aprs amateur (needs Joshua's licence, callsign, Direwolf + radio interface)
- [ ] status shows Direwolf connected; receive of local packets decoded
- [ ] TX only after Joshua presses Send; indicator shows QUEUED (never ON-AIR)
- [ ] a message to another station is heard/digipeated and acked (check aprs.fi independently)
- [ ] retry schedule matches settings; cancel stops retries

## task-aprs GMRS
- [ ] BLOCKED: no compliant, controllable GMRS data hardware identified (see GMRS-HARDWARE-RESEARCH.md).
  Only the simulation exists. No GMRS transmission has been done or should be attempted.

## task-sdr
- [ ] RTL-SDR enumerated; WFM broadcast station audible; NFM/AM/SSB demod usable
- [ ] the Direwolf sound card is not offered as SDR audio output
- [ ] unplugging the dongle shows an error, no crash
