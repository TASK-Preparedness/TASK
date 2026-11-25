# T.A.S.K. SDR Studio (task-sdr 0.2.0) — Phase 4G

An original native receiver. It is inspired by the *workflow* of SDR++ (tuner on top, spectrum and waterfall, side panels); no SDR++ code, assets or artwork are used. All drawing is our own QPainter code with the palette #101722 / #78dce8 / #27374b. **Receive only:** no transmit code path exists in any backend.

## Milestones
| Milestone | Scope | Status |
|---|---|---|
| **M1** | Native RTL-SDR backend, pluggable backends with stubs, safe discovery, background DSP with bounded queues, digit tuner, AM/NFM/WFM/USB/LSB/CW, bandwidth, gain/AGC, squelch, volume/audio, S-meter, bookmarks/presets | **Delivered** (mock + synthetic-IQ tested) |
| M2 | Smart Scanner (FAST, 4 s hold resetting on activity, Scan/Resume, persistent/session Ignore with tolerance and review list, 50-entry history with pins, adaptive noise floor + squelch + VAD with squelch-only fallback, pre-buffer, measured benchmarks) | **Delivered in 0.2.1** (see docs/phase4g-m2/SMART-SCANNER.md) |
| M3 | Offline, source-attributed US frequency overlays, labelled by data type (allocation / band plan / published channel / verified local / user) | Not started; needs verified datasets with sources |
| M4 | Recording (WAV/FLAC/IQ+SigMF), history/playback, multi-receiver | Not started |

## SDR tile and routing
The SDR tile is unchanged: it still runs `/usr/bin/task-sdr`. That binary is now SDR Studio, a separate process. It is not embedded in the launcher, by design:
* radio ownership and USB I/O stay out of the launcher;
* a DSP crash cannot take down the home screen;
* the existing tile routing and all 12 tiles stay identical.

## RTL-SDR Blog V4 — verified facts
* **Range:** 500 kHz – 1.766 GHz (RTL-SDR Blog V4 datasheet, rtl-sdr.com). HF from 0.5 to 28.8 MHz goes through a built-in 28.8 MHz upconverter. The driver applies it automatically: no direct sampling, no offset.

  The brief's "~24 MHz" is the floor for *other* R820T/V3 sticks without direct sampling. Studio applies it to non-V4 devices (profile "RTL-SDR (R820T/R860)", 24–1766 MHz). 2.4 GHz and 5.8 GHz are always rejected; tests check this.
* **Driver:**
  * The V4 needs a librtlsdr with V4 support. Osmocom rtl-sdr has merged it upstream.
  * Debian **trixie** ships `librtlsdr0 2.0.2-2+b1` (packages.debian.org), so the rtl-sdr-blog fork is **not** needed on trixie. The task-sdr deb therefore Depends on `librtlsdr0 (>= 2.0.2)`.
  * Debian bookworm's 0.6.0-4 lacks V4 support.
  * The fork (github.com/rtlsdrblog/rtl-sdr-blog) stays an option, built from source; it is not packaged by us.
* Detection uses the USB strings: manufacturer "RTLSDRBlog", product "Blog V4". These are the same strings the driver checks.
* **Never called:**
  * `rtlsdr_set_bias_tee*` — the bias tee would power an antenna LNA;
  * direct sampling;
  * test mode;
  * EEPROM writes.

  Only the receive symbols listed in `backends/rtlsdr.py` are bound.

## Architecture
* **`task_sdr/backends`:**
  * `Backend` (available / enumerate / open) and `DeviceProfile` (verified range, rates);
  * `rtlsdr` (ctypes), `soapy` (optional; used only if `python3-soapysdr` is present), `simulated`;
  * marked stubs: airspy, sdrplay, hackrf, lime, pluto, uhd, network.
* **Discovery** never opens or claims a device. It calls only `get_device_count`, `get_device_name` and `get_device_usb_strings`.
* **Engine worker thread:** read → spectrum FFT → channel power → demodulate → AGC → squelch. Results go into bounded queues: frames `deque(maxlen=3)`, audio `Queue(24)` (drop-oldest, counted). The GUI timer (30 ms) takes the newest frame and the pending audio. The worker never touches Qt.
* **Tuner:** 11 digits `GG.MMM.kkk.hhh` with small separators.
  * Mouse: click the top half of a digit for +1 and the bottom half for −1 (integer carry/borrow).
  * Wheel and keyboard: Left/Right, Up/Down, 0–9; Enter/F to type 146.52M / 1.2G / 162550000 / 00.162.550.000.
  * Out-of-range steps are **rejected** (the value stays unchanged and the reason is shown); never clamped or wrapped.
* **DSP** (scipy): WFM/NFM/AM/USB/LSB from 0.1.0, plus CW (700 Hz BFO, 100–1500 Hz filter). User bandwidth is per mode. Audio AGC. The S-meter is **uncalibrated**: dBFS in the channel, S9 = −30 dBFS by default, 6 dB per S unit.
* **Audio:** QtMultimedia, 48 kHz. The Direwolf card stays excluded, as in 0.1.0.

## Limitations (M1)
* No direct-sampling HF for V3 or other non-V4 sticks.
* The S-meter is not calibrated in dBm.
* Sample rate is fixed at 1.024 Msps (the pref exists; there is no UI yet).
* Waterfall colour range is fixed (−110 to −20 dBFS).
* Everything except the synthetic and mock paths is **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**.
