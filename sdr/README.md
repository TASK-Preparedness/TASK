# task-sdr 0.1.0 (receive only)

SoapySDR (python3-soapysdr + soapysdr-module-rtlsdr) device layer, scipy.signal demodulators (WFM/NFM/AM/USB/LSB),
QtMultimedia QAudioSink output (Direwolf's sound card excluded), spectrum + waterfall, presets, persistent prefs,
busy/unplug handling, DeviceClaim ownership, status card `task-sdr`. No transmit API is used anywhere.
`task-sdr --simulate` runs on synthetic signals. Real-hardware tests S1–S9: UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.
CPU/latency on the Pi: not measured (estimate 15–50 % of one core).
