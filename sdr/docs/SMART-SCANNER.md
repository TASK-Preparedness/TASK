# SDR Studio: Smart Scanner (task-sdr 0.2.2)

Receive only. task-sdr has no transmit code path. Hardware status: **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**.
Nothing in this document was measured on a Raspberry Pi 5 or with an RTL-SDR Blog V4.

## 1. What changed from 0.2.1

| Area | 0.2.1 | 0.2.2 |
|---|---|---|
| Ignore tolerance | one global tolerance | Per entry: **exact (0 Hz)** is the default. Set it in Hz or kHz. The effective tolerance is always capped at `(spacing - 1) // 2`, below half the channel spacing (for bookmark scans, below half the closest pair), so an ignore can never cover a neighbouring channel. |
| Ignore kinds | session / persistent | Labelled **Session** (until the scan stops / app closes) and **Always** (saved in prefs). The review list shows: frequency, kind, set and effective tolerance, and a label. Actions: *Set tolerance*, *Make Always*, *Make Session*, *Remove* (removes exactly one entry, keyed by frequency). |
| Migration | — | 0.2.1 `scan_ignores` (plain Hz integers) load as **Always, exact 0 Hz**, with nothing lost. 0.2.2 also keeps writing the legacy list, so a rollback to 0.2.1 keeps your ignores; only the per-entry tolerances are lost on rollback. |
| History | list with pins | 50 entries, newest first; pinned entries are never pushed out. Actions as buttons **and** a context menu: Retune, Ignore (session), Ignore always, Un-ignore, Add bookmark, Remove bookmark, Pin/Unpin, Clear unpinned. **Retune** stops the scan and tunes the receiver; it never starts or stops recording. |
| Dead/carrier release | always on (VAD dead-carrier) | **"Release silent carrier after N s" is optional and OFF by default.** When off, only the 4 s hold (restarted by activity) releases a channel. When on, a channel is released only when the voice detector reports no voice for N s. |
| Controls | Scan, Pause/Resume-skip | **Scan / Stop, Pause, Resume, Skip** with one documented state machine (below). |

## 2. State machine (tested by `tests/test_scanner_022.py::test_t01_state_machine_table`, 5 states × 5 commands)

Exactly the `TRANSITIONS` table in `task_sdr/scanner.py` (paused/S = paused from scanning, paused/L = paused from locked). "—" means the command is refused and the state does not change.

| From \ command | scan | stop | pause | resume | skip |
|---|---|---|---|---|---|
| idle | scanning | — | — | — | — |
| scanning | scanning (restart) | idle | paused/S | — | scanning (next span) |
| locked | scanning (restart) | idle | paused/L | — | scanning (channel released as "skipped") |
| paused/S | scanning (restart) | idle | — | scanning | scanning |
| paused/L | scanning (restart) | idle | — | locked (hold restarts at 4 s) | scanning (released) |

Automatic transitions: scanning → locked on activity above squelch on a channel that is not ignored; locked → scanning when the 4 s hold expires (or the optional carrier timeout fires).

The hold timer never runs while paused. Nothing starts scanning by itself: the scanner starts only from the Scan button.

## 3. Evidence, kept in separate categories

| Category | What it is | Status |
|---|---|---|
| A. Synthetic unit tests | `sdr/tests/` (84 tests): state machine, ignores and caps (boundaries: exact 0 Hz matches only f, ±1 Hz misses; at 12.5 kHz spacing, cap 6 249 Hz matches and 6 250 Hz and the adjacent channel do not; a 100 kHz ignore still lets the adjacent channel lock), migration, carrier timeout off/on, history 50 + pins, live UI widgets with a mocked engine. | PASS on the build box (x86_64). |
| B. Mocked driver | The engine and scanner run against a fake librtlsdr device feeding generated IQ. No USB, no tuner. | PASS (inside A). Says nothing about real tuner timing. |
| C. x86 bench | `sdr/bench/bench_scanner.py` on this build box, synthetic traffic, real `Engine.scan_step` path. Results: `bench/results-0.2.2/`. | Measured (x86 only), see §4. |
| D. Raspberry Pi 5 measurements | Protocol in §5. | **PENDING — not measured.** |
| E. RTL-SDR Blog V4 measurements | Protocol in §5. | **PENDING — not measured.** |

Nothing in A–C shows how many transmissions a real receiver would miss. The bench counts misses **only against its own synthetic traffic, with ideal zero-time retunes (or an assumed 5 ms) and perfect signals**. Real-world miss rates are unknown until D and E are done.

## 4. x86 bench (category C only; NOT a Pi, NOT real RF)

| Metric (task-sdr 0.2.2, retune latency 0 ms, seed 3) | Light: 20 tx / 300 s | Heavy: 75 tx / 300 s |
|---|---|---|
| Host | x86_64  8 cpus, python 3.13.5 | x86_64  8 cpus, python 3.13.5 |
| Synthetic receive time | 300.0 s | 300.0 s |
| Wall time | 74.7 s | 84.07 s |
| CPU per second of IQ (1.0 = one core) | 0.249 | 0.28 |
| Real-time headroom | 4.0× | 3.6× |
| Python heap peak (tracemalloc) | 1.03 MiB | 1.04 MiB |
| Process max RSS | 107.4 MiB | 107.1 MiB |
| Channels / spans per pass | 321 / 5 | 321 / 5 |
| Idle revisit (full band) | 80.0 ms | 80.0 ms |
| Synthetic transmissions | 20 | 75 |
| Detected | 16 | 39 |
| Not detected: receiver held on another channel | 4 | 36 |
| Not detected while sweeping (synthetic only) | 0 | 0 |
| Detection latency median / max | 52.4 / 3870.5 ms | 772.7 / 5355.8 ms |
| carrier_timeout_releases | 0 | 0 |

Notes:
* "Missed: receiver busy" means the single receiver was held on another channel. That always happens with one receiver plus a 4 s hold. "Missed while sweeping" is 0 **in this synthetic setup only**. Do not read it as a real-world figure.
* The carrier timeout is OFF (the default), so `carrier_timeout_releases` is 0.
* The CPU figure is single-threaded on an x86 build box. A Pi 5 will be several times slower. Measure it (§5).

## 5. Physical measurement protocol (to be done by a person with the hardware)

Setup: Raspberry Pi 5 (record RAM, cooling, OS image, `uname -a`), RTL-SDR Blog V4 (record serial and firmware string from `rtl_test -t`, no transmission). A known local signal source you are licensed to use, or published broadcast/NOAA/aviation signals. **Never transmit to run these tests.** Start task-sdr by hand. Nothing autostarts.

| # | Measurement | Method | Pass guide |
|---|---|---|---|
| P1 | Dwell time per span | Debug log `scan dwell` timestamps over 2 min idle scanning 144–148 MHz @ 12.5 kHz | record |
| P2 | Retune settle | Tune between two spans 2 MHz apart 100×. Time from `set_center_freq` until the PSD of a steady carrier is within 1 dB of steady state. | Is one discarded block (8 ms) enough? |
| P3 | CPU | `pidstat -u -p <pid> 1 120` while scanning idle, and while locked on audio | < 60 % of one core |
| P4 | Memory | `ps -o rss= -p <pid>` at 0, 10, 30, 60 min | no growth > 10 MiB/h |
| P5 | Misses | Key N=30 known transmissions (2–5 s, spaced ≥ 10 s apart) on bookmarked channels; count those heard | record detected / missed, and why |
| P6 | Detection latency | Phone stopwatch or audio capture: key-up to lock indicator, 10 samples | record median / max |
| P7 | Ignore boundaries | Ignore the exact channel and confirm the adjacent channel (one step away) still locks | adjacent must lock |
| P8 | Carrier timeout | Default OFF: an unmodulated carrier is held while present. ON at 5 s: it is released ≈ 5 s after voice stops | as described |

### Results: Raspberry Pi 5 (PENDING)

| # | Value | Date | Tester | Notes |
|---|---|---|---|---|
| P1 | | | | |
| P2 | | | | |
| P3 | | | | |
| P4 | | | | |
| P5 | | | | |
| P6 | | | | |
| P7 | | | | |
| P8 | | | | |

### Results: RTL-SDR Blog V4 specifics (PENDING)

| Item | Value | Date | Tester | Notes |
|---|---|---|---|---|
| Tuner reported (R828D) | | | | |
| Retune settle at 2.4 MS/s (P2) | | | | |
| Lowest usable gain without overload at site | | | | |
| Samples dropped (librtlsdr async) over 30 min | | | | |

## 6. Limitations
* One receiver: transmissions that overlap a lock or hold are missed.
* The settle constant (`SETTLE_BLOCKS` = 1 block, ≈ 8 ms) is not validated on hardware.
* Tolerance applies to scan matching only. It never mutes a channel you tune by hand.
