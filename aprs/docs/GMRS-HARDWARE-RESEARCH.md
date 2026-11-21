# GMRS data — hardware research and blocker (2026-10-12)

**Status: GMRS profile, driver interface and SIMULATED driver are implemented and tested. Real GMRS data TX is
NOT complete: no certified GMRS hand-held with a documented, software-controllable data interface was found.**
Nothing below is guessed; every fact has a source. "Not found" means not found in the cited sources.

## Rules applied (47 CFR Part 95, eCFR fetched 2026-10-12)
§95.1731(d) data only from hand-held portable units (location, location request, brief text to a specific unit);
§95.1787(a) radio design: ≤ 1 s burst, ≤ 1 per 30 s (auto-reply exception), non-removable integral antenna,
no data on 467 MHz main channels; §95.1773(c) channels; §95.1733(a)(9) no messages to amateur stations;
§95.339 no external device that makes the combination non-compliant (→ no Direwolf/sound-card modem on GMRS).
Source: https://www.ecfr.gov/current/title-47/chapter-I/subchapter-D/part-95/subpart-E

## Candidates
| Radio | Service / type | Built-in data | Host control interface | Usable by T.A.S.K.? |
|---|---|---|---|---|
| BTECH GMRS-PRO (FCC ID 2AGND-GMRS-PRO) | GMRS hand-held | Yes: text + GPS location to other GMRS-PRO units (https://baofengtech.com/product/gmrs-pro/); proprietary digital codec, not Rino-compatible (BTECH blog) | Programmed through the BTECH phone app over Bluetooth. Only an unofficial reverse-engineered library exists: benlink (https://github.com/khusmann/benlink, docs https://benlink.kylehusmann.com/benlink.html) — lists GMRS-PRO as **untested**; exposes TNC data/position/beacon settings, **no documented GMRS text/location message call** | **Best candidate. Blocker:** no documented/verified API to make the radio send its own GMRS text/location packet. Antenna: reported integral/glued on most units, some reports of removable (myGMRS forum topics 5902, 7401) — must be checked against the FCC grant per unit |
| Garmin Rino 750/750t/755t | GMRS hand-held (US) | Yes: peer-to-peer position (sent on PTT/call, ≥ 30 s apart, not on repeater channels), unit-to-unit text (https://www8.garmin.com/manuals/webhelp/rino750/EN-US/Rino_75x_OM_EN-US.pdf; specs page GUID-71B065D1…) | ANT+ / Bluetooth for Garmin apps; no documented third-party control API found | Compliant data function, but **no software control path** found |
| Motorola Talkabout T800 | **FRS** (not GMRS) (data sheet: "FRS 462-467 MHz") | Text + location via Talkabout app, radio used "as a modem" over BLE 4.2 (user guide MN009246A01) | Proprietary app protocol, undocumented | Not a GMRS radio; out of scope for the GMRS profile |
| Midland GXT67 PRO; Rocky Talkie Expedition | GMRS hand-held | No GPS/text/data listed (https://midlandusa.com/products/gxt67-pro-gmrs-5-watt-walkie-talkie, https://rockytalkie.com/products/expedition-radio) | — | No |
| Midland MXT575 | GMRS **mobile** | GPS location sharing between Midland units under FCC waiver DA 23-633 (WT Docket 21-388, 2023-07-24): Midland equipment only, 462 MHz main/interstitial, ≤ 50 ms per 10 s, only when users are linked through a smartphone app, channel-clear detection | Midland app; undocumented | Waiver covers Midland's own design only; no third-party control path. Not usable |
| Radioddity DB25-G | GMRS **mobile**, 25 W, SO-239 detachable antenna (https://www.radioddity.com/products/radioddity-db25g; manual https://radioddity.s3.amazonaws.com/Radioddity_DB25-G_User_Manual_20210823.pdf) | **None** (no GPS/text); DATA jack is the programming port (CHIRP / Radioddity CPS) | Programming only | **No GMRS data allowed** (mobile + detachable antenna, §95.1731(d), §95.1787(a)(4)); feeding it a Direwolf modem would violate §95.339. RX/voice only |

## What is implemented
* `task_aprs.gmrs.driver.GmrsDriver` interface: capabilities (hand-held, integral antenna, built-in data, which
  kinds, max burst, verified_on_hardware), `request_transmit()` asks the radio to send its own packet, RX callback.
* `SimulatedGmrsDriver` (`task-aprs --gmrs-simulation`): records requests, injects RX; labelled SIMULATION.
* Policy (`task_comms.txpolicy.evaluate_gmrs`) + `GmrsTx`: separate config (`gmrs.toml`), separate attestation and
  GMRS call sign, separate audit (`audit-gmrs.jsonl`), TX off by default, auto-reply off by default, explicit
  user action, channel allow-list, ≤ 1 s, ≥ 30 s, recipient required for text, amateur recipients refused,
  external modems refused, unverified real drivers refused, voice-ID reminders.

## To close the blocker (UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST)
1. Obtain a GMRS-PRO; read its FCC grant (fccid.io/2AGND-GMRS-PRO) to confirm integral antenna and data function.
2. Capture the BTECH app's BLE traffic while sending a GMRS text and location (own radios, dummy load).
3. Only if the radio itself generates the packet on command: write `gmrs/btech.py` driver, bench-test on a dummy
   load, set `verified_on_hardware` only after Joshua signs off. Until then transmit stays refused
   (`driver-unverified`).
