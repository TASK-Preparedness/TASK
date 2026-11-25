# SDR Studio 0.2.4 — receive audio pipeline

Status: **HARDWARE VALIDATION PENDING**. Everything below was measured on an x86 build box with synthetic IQ. None of it was measured on a Raspberry Pi with an RTL-SDR Blog V4.

## Data path (0.2.4)
```
RTL-SDR ──read_sync 16384 IQ──▶ READER thread ──bounded deque (48 blocks ≈ 0.77 s)──▶ DSP thread
   (never demodulates; reads back to back)        drops OLDEST when full, counted        accumulates 65536 IQ
                                                                                          shift → channel FIR (overlap-save)
                                                                                          → decimate → FM discriminator (75 kHz = 1.0)
                                                                                          → 75 µs de-emphasis → 15 kHz audio LPF
                                                                                          → polyphase resample to 48 kHz (continuous)
                                                                                          → squelch → AGC → volume → counted clip
                                                                                          ▼
                                                       AudioRing (thread-safe; target 150 ms, cap 500 ms)
                                                                                          ▼
                                       QAudioSink PULL mode (QIODevice.readData), Qt audio thread
                                       (push mode: 10 ms pump, honours bytesFree/partial writes)
```
* The GUI timer (30 ms) only draws the display. In pull mode it never touches audio.
* **Retune:** a generation counter is bumped. IQ read before the retune is counted as `iq_stale_blocks` and is not demodulated.
* **Overrun** (no consumer, or a slow sink): the oldest audio is dropped to hold the latency cap. The drop is counted in `audio_overrun_*`.
* **Underrun:** silence is inserted and counted in `audio_underrun_*`. The ring then refills to its 150 ms target before playing again, so you get one gap instead of continuous crackle. The fill before the first audio is counted separately (`audio_startup_fill_samples`).
* **Device loss:** a dongle unplug closes the device and the reader reopens it every second. A sink `StoppedState` with an error, or a change in the audio-output list, restarts the sink after 1 s. Restarts are counted.
* **Audio mode:** pull is the default. Push is available with `--audio-mode push` or `TASK_SDR_AUDIO_MODE=push`.

## Diagnostics
Run `task-sdr --diag-log ~/sdr-diag.jsonl`, or set `TASK_SDR_DIAG_LOG`. It writes one JSON line per second with these fields:
* IQ: `iq_rate_ratio`, `iq_dropped_*`, `iq_stale_blocks`, `read_errors`
* DSP: `dsp_avg_ms`, `dsp_max_ms`, `dsp_over_budget`
* Levels: `demod_rms_dbfs`, `audio_rms_dbfs`, `audio_peak_dbfs`, `clipped_samples`, `agc_gain_db`
* Audio ring: `audio_queue_ms`, `audio_underrun_*`, `audio_overrun_*`
* Sink: `sink_*` (mode, buffer size, bytes free, partial writes, restarts)
* `latency_ms_est`

Logging is off by default and writes only to the path you give it.

## Levels
* **WFM discriminator:** full 75 kHz deviation = 1.0.
* **AGC:**
  * Target: 0.25 RMS (≈ −12 dBFS)
  * Attack: 30 ms
  * Release: 1.5 s, smoothed in dB
  * Gain range: 0.1–50
  * The gain ramps per sample, and an instantaneous limiter keeps |out| ≤ 0.95.
* **With AGC off:** the level follows the station's deviation. Full deviation is about −3 dBFS RMS for a tone.

## Known limits
* **AM:** the DC tracker is still per-block, so the output is not exactly block-size invariant. The error is ≤ 0.025 and inaudible in tests.
* **Latency:** about 150–250 ms of app-side latency (ring target plus the sink buffer) by design.
