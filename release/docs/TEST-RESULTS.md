# Test results (Phase 4C, 2026-10-12): only the tests that actually ran

All of these ran on the x86_64 development box with **no radio, SDR, GPS, Meshtastic node or Pi**.
Nothing ran on the Raspberry Pi. Everything that needs hardware is listed in HARDWARE-CHECKLIST.md as
UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.

| suite | env | result | kind |
|---|---|---|---|
| platform core + migration (tests/) | Python 3.13 venv, PySide6 offscreen | 178 passed | automated; migration in sandbox root |
| console (console/tests) | same | 51 passed | automated |
| launcher 0.3.0 (launcher/tests) | same | 284 passed, 13 skipped | automated (UI offscreen) |
| maps 0.1.1 (maps/tests) | same | 132 passed | automated; online tiles from a local fake HTTP server |
| comms (comms/tests) | Debian python3 | 16 passed | automated |
| task-aprs (aprs/tests) | venv | 35 passed | simulated: fake Direwolf AGW server on 127.0.0.1; GMRS simulated driver only |
| task-sdr (sdr/tests) | Debian python3 + numpy/scipy/SoapySDR | 19 passed | simulated: FakeDevice IQ, synthetic signals |
| task-mesh 0.2.0 (task-mesh repo) | Debian python3 + vendored meshtastic | 313 passed* | automated + simulated node |

\* pytest progress showed 313 tests passing (100%, no failures or errors); the closing summary line was not
captured in the log of the final run.

Not run: lintian (it could not start on the dev box: missing Perl module), installation via apt/dpkg,
any RF test, any test on arm64. The debs were checked with `dpkg-deb -f/-c`, extracted into a scratch root,
and each Python package imported from there.

GMRS: the TX path is tested only against the simulated driver. **Real GMRS transmission is NOT complete**:
no compliant controllable hardware was identified (GMRS-HARDWARE-RESEARCH.md).
