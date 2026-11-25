# task-sdr 0.2.3: frequency-handling audit

Scope: tuner, scanner, bookmarks, history, ignores, overlays, presets, settings JSON, Qt signals/slots, spinboxes and
validators, numpy dtypes, SigMF/metadata. Rule after the audit: **a frequency is an exact Python integer number of Hz**
(arbitrary precision). It is checked by `task_sdr.freq.hz()`, which refuses float, str, bool, None, NaN and inf
instead of coercing them. Each receiver's own range is then applied by `DeviceProfile.check()`; per-receiver limits
are unchanged (RTL-SDR Blog V4 0.5 MHz–1.766 GHz, generic R820T 24 MHz–1.766 GHz).
`ABS_MAX_HZ` (99 999 999 999, the 11-digit display) is only a type/display bound.

Before this audit, every receiver profile topped out at 1.766 GHz, below 2^31. So none of the 32-bit issues below
could be triggered by tuning a supported receiver. They could be triggered by typed text, a hand-edited
prefs.json, overlay data, or a future wide-range receiver.

| # | Area | Finding (before) | Change |
|---|---|---|---|
| A1 | Qt signals | `TunerWidget.changed`, `SpectrumWaterfall.tuneRequested` and `ScannerPanel.tuneRequested` were `Signal(int)` (32-bit C int): values ≥ 2^31 overflow with a shiboken error. The new overlay panel had the same defect, found by its tests. | All four are `Signal(object)` (Python int, exact). A test scans the source for frequency `Signal(int/float)`. |
| A2 | Tuner text entry | `round(float(text) * 1e6)`: binary float rounding. A long digit string gave `float → inf → round()` **OverflowError**, which escaped the `ValueError` handler. | Exact `Decimal` arithmetic (half-even to 1 Hz); 40-character cap; only `ValueError` escapes. |
| A3 | Receiver range check | `int(hz)` coercion: floats were truncated silently, bools and numeric strings were accepted, NaN raised `ValueError` and inf raised `OverflowError` (not `RangeError`), so the UI's tune handler could raise. | Strict check; any invalid value is a `RangeError` with a reason; `accepts()` never raises. |
| A4 | Settings JSON (prefs.json) | Same `int()` coercion for freq_hz, bandwidth and step; sample_rate, scan start/stop, bookmark and preset entries were not validated; ignores accepted `true`/negative/huge values; `Infinity` gave an uncaught OverflowError path. | Every Hz field is strictly checked. A bad scalar resets to defaults (as before). A bad **list entry** (bookmark/preset/ignore) is dropped on its own and the user's valid entries are kept. Exact round-trip of >2^32 values is tested. |
| A5 | Scanner and ignores | `ScanConfig` and `IgnoreList` coerced with `int()` (accepted 146.5e6, True, "146000000"). | Strict; ignore matching is exact across 2^32 (no wrap). |
| A6 | librtlsdr (ctypes) | `rtlsdr_set_center_freq` takes `uint32`; ctypes silently wraps values ≥ 2^32 (2^32+1 → 1 Hz). Reachable only if a profile allowed it. | Explicit guard after the profile check: anything ≥ 2^32 is refused before the call. |
| A7 | SoapySDR | `setFrequency(float(hz))`: IEEE double is exact for integers < 2^53 (9×10^15 Hz). | No change needed. |
| A8 | numpy dtypes | Frequencies are never stored in numpy arrays. float32 arrays hold dB spectra and audio only. Pixel↔Hz mapping uses Python float64 (sub-Hz exact at 6 GHz). The scanner's channel offsets are int minus int, then float64. | No change; tested at 1.766 GHz and 5.999 GHz. |
| A9 | Spinboxes / validators | Bandwidth `QSpinBox` (≤ 250 kHz), gain, squelch, volume and carrier timeout are not frequencies and are far below 2^31. The ignore-tolerance `QDoubleSpinBox` (3 decimals, Hz or kHz) is converted with `round()` and capped at 1 MHz by `IgnoreList`. No `QValidator` is used; the tuner is a custom widget, not a spinbox. | No change needed. |
| A10 | SigMF / metadata | task-sdr writes **no** IQ recordings, SigMF or other frequency metadata. The only persisted frequency text is the status summary string ("146.5200 MHz NFM"). | Not applicable. If IQ recording is added later, `core:frequency` must be written from the integer Hz. |
| A11 | Overlays | Strict from the start: integer Hz 1 Hz–6 GHz; floats, strings and bools rejected; whole-file rejection. | Overlay tune uses the same strict path; a confirmed tune outside the receiver is rejected. |
| A12 | History / bookmarks / presets | Values come from internal ints or prefs (now validated). Retune goes through `MainWindow.tune` → strict check. | Covered by A1/A3/A4. |

Behaviour changes a user could notice: an invalid bookmark, preset or ignore in a hand-edited prefs.json is now
dropped by itself, where before it was kept or caused a crash later. It disappears from the file on the next save.

Tests: `sdr/tests/test_freq_023.py` (99 cases) covers >2^31, >2^32, 2^32±1 carry, negatives, NaN/±inf, floats
(including integral floats), strings, bools, 10 000-character strings, GHz precision in parsing and in pixel mapping,
out-of-range values per receiver, prefs JSON specials (NaN, Infinity, 1e400, 5000-digit numbers), list sanitising,
signal transport of exact 64-bit values, the uint32 guard, and overlay isolation.
