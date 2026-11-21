# Hardware compatibility

Status words: **verified** (tested on real hardware with T.A.S.K.), **untested**
(expected to work, nobody has confirmed), **experimental** (may work with
limits), **unsupported**. Please report your results with the *Hardware
compatibility report* issue template — that is how entries move to verified.

Anything marked untested or experimental is: **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**.

## Computers

| Board | OS | Status | Notes |
|---|---|---|---|
| Raspberry Pi 5 (8 GB) | Debian 13 trixie arm64 (kernel 6.18 rpt), X11 desktop | **verified** for the installed modules | The development system. The new installer itself has not run on it yet. |
| Raspberry Pi 5 (2/4/16 GB) | Debian 13 / Raspberry Pi OS 64-bit (trixie) | untested | 2 GB may be tight with SDR Studio + WebEngine reader. |
| Raspberry Pi 500 / CM5 | same | untested | |
| Raspberry Pi 4 / 400 / CM4 | same | untested | 4 GB+ recommended. |
| Raspberry Pi 3 / 3B+ / CM3 | same | experimental | 1 GB: installer skips the QtWebEngine reader; SDR Studio not recommended. |
| Raspberry Pi Zero 2 W | same | experimental | 512 MB: Minimal installation only. |
| Raspberry Pi 1, 2, Zero, Zero W | any | unsupported | No 64-bit userland target. |
| Any board with a 32-bit (armhf) OS | any | unsupported | Packages are arm64 only — even on a 64-bit kernel. |
| Debian 12 bookworm or older | any | unsupported | Needs Python ≥ 3.13 and PySide6 ≥ 6.8 from trixie. |
| Windows 11 x64 PC | — | unavailable | See WINDOWS.md. |

The installer enforces architecture (arm64) and OS (Debian 13 trixie) from what it
**detects**; choosing a model by hand can never bypass those checks.

## Radios, receivers and accessories

| Device | Used by | Status | Notes |
|---|---|---|---|
| Heltec WiFi LoRa 32 V3 (915 MHz), CP2102 USB | Mesh | **verified** (Meshtastic over USB serial, owned by `task-mesh-service`) | First approved Firmware Manager test device (planned; no flashing exists). |
| Heltec V3.2 | Mesh | untested | |
| LILYGO T-Beam (915 MHz) | Mesh | untested | |
| LILYGO T-Deck (915 MHz) | Mesh | untested | |
| Other Meshtastic USB-serial nodes | Mesh | untested | |
| MeshCore nodes | Mesh | experimental | Protocol code exists; hardware not confirmed. |
| u-blox 7 USB GPS (via gpsd) | Maps & GPS | **verified** | gpsd owns the device; T.A.S.K. reads gpsd only. |
| Other gpsd-supported GPS receivers | Maps & GPS | untested | |
| RTL-SDR (RTL2832U-family) | SDR Studio | untested with SDR Studio 0.2.4 — **physical acceptance test pending** | Receive only. SDR++/Gqrx on the dev Pi are left untouched. |
| RTL-SDR Blog V4 | SDR Studio | untested specifically | Needs a SoapySDR/librtlsdr build that supports the V4 tuner. |
| Direwolf soundcard TNC + radio | Radio / APRS | experimental | Receive path in use; transmit only by explicit action. |
| BTECH UV-PRO (Bluetooth) | Radio / APRS | **unverified** | A Bluetooth Serial Port service is advertised, but it has **not** been confirmed to be a KISS TNC. No support is claimed. |
| GMRS data radios | Radio (GMRS profile) | experimental (simulated driver only) | Kept separate from amateur APRS. |

## Device ownership and safety

* Discovery reads `/sys` and `/proc` only; it never opens serial ports (opening
  can reset an ESP32 node), Bluetooth sockets, SDRs or GPS devices.
* task-core assigns each device to one owner; apps never steal a device another
  service owns (e.g. gpsd's GPS or `task-mesh-service`'s Heltec).
* Nothing transmits without explicit operator action; amateur transmit requires
  your own callsign and attestation. No automatic beacons, digipeating or acknowledgements.
