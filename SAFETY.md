# Safety and legal precautions

> **EXPERIMENTAL ALPHA — NOT VALIDATED ON A PHYSICAL RASPBERRY PI.**
>
> T.A.S.K. is experimental software. It can crash, lose data, or behave
> unexpectedly. It is not a certified emergency system.

This is practical guidance, **not legal advice**. Radio rules vary by country
and change over time. You are responsible for following the law where you
operate.

## 1. This is not a substitute for emergency services

If someone is in immediate danger, call **911** (or the local emergency number
where you are). T.A.S.K. must not be your only plan for calling for help,
navigation, or medical information. Offline medical references are not a
diagnosis and do not replace a clinician.

## 2. Receive-only by default

T.A.S.K. is designed so that **nothing transmits on a radio unless you
explicitly tell it to**.

* SDR Studio is receive-only.
* Mesh messaging over a USB Meshtastic node can send only when you compose and
  send a message (and the node itself is under your control).
* Radio / APRS transmit stays off until you enter your own licensed callsign
  and enable it. There are no automatic beacons, digipeaters, or
  acknowledgements added by T.A.S.K.
* The installer and Debian packages do not flash firmware, do not change radio
  configuration files, do not enable background services, and do not start
  anything at boot.
* Device discovery reads `/sys` and `/proc` only. It does not open serial
  ports, Bluetooth sockets, SDRs, or GPS devices just to look for hardware
  (opening a serial port can reset some ESP32 nodes).

If you see unexpected transmit, RF, or service-start behaviour, stop using the
software and report it privately as described in [SECURITY.md](SECURITY.md).

## 3. Do not transmit without a license and without knowing the rules

Unlicensed or out-of-band transmission can interfere with other people,
including emergency and aviation communications, and can be unlawful.

### Amateur (ham) radio

In the United States, transmitting on amateur frequencies generally requires
an amateur license issued by the FCC, and you must identify with your own
callsign as required by the rules (see FCC Part 97). Other countries have
their own amateur regulators and licence classes. T.A.S.K. may ask for a
callsign before enabling amateur transmit; that is a software guard, not a
substitute for a real license or for knowing the band plan, power limits, and
identification rules.

### GMRS and other personal radio services

GMRS in the United States generally requires a GMRS license. FRS, MURS, CB,
and similar services have their own rules, channels, and power limits. Do not
assume that a radio bundled with a Pi project is legal to key up on a given
band. T.A.S.K.'s GMRS data profile is experimental and, in this alpha, uses a
simulated driver only.

### Meshtastic, LoRa, and ISM-band devices

A USB Meshtastic (or similar) node transmits over LoRa when it sends or
routes traffic. You must use hardware and settings that are legal in your
country (frequency, power, duty cycle). "Meshtastic" is a trademark of the
Meshtastic project; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

### SDR

SDR Studio in T.A.S.K. is receive-only. Do not attach a transmit-capable SDR
chain and expect this software to make it legal or safe. Reception of some
services may still be restricted in some places.

## 4. Back up data and use a spare system

* Test this alpha on a **spare SD card**, not a production system and not the
  only copy of your files.
* Back up configuration and data you care about (`~/.config/task-*`,
  `~/.local/share/task-*`, `/etc/task`, maps, ZIM libraries, message history)
  before installing, upgrading, or removing packages.
* Uninstall and rollback steps are in [INSTALL.md](INSTALL.md). Prefer
  `apt-get remove` over `purge`, and do not run `apt-get autoremove` just to
  uninstall T.A.S.K.
* The public packages have not been validated on a physical Raspberry Pi.
  Expect breakage.

## 5. Privacy and operational security

Mesh messages, GPS tracks, APRS, and logs can reveal your location, your
callsign, and who you talk to. Redact that information before filing a public
issue. Do not commit secrets, radio configs, or personal files to a clone of
this repository. See [CONTRIBUTING.md](CONTRIBUTING.md) and [SUPPORT.md](SUPPORT.md).

## 6. Medical and library content

T.A.S.K. does not ship maps, ZIM files, or medical references. Anything you
add is under that work's own license and comes with its own accuracy limits.
The reader is experimental. Do not treat it as a complete or current medical
authority.

## 7. If something seems unsafe

1. Stop transmitting. Power down or unplug radios if needed.
2. Take the spare card out and return to a known-good card if the system is
   unstable.
3. For vulnerabilities or unexpected RF / privilege issues, use the private
   path in [SECURITY.md](SECURITY.md).
4. For ordinary bugs and test results, use the public issue templates.
