# Quick start

1. **Check compatibility:** `cd installers/raspberry-pi && /usr/bin/python3 -m task_installer detect`.
2. **Open the launcher:** after installation, choose *T.A.S.K.* from the applications menu (or run `task-launcher`).
3. **Mesh:** plug in your Meshtastic node, open *Mesh Network*, pick the device. The background
   message service is optional; enable it yourself from *Mesh → Network Status* if you want
   messages while the window is closed. For a loud audible alert, run `scripts/generate-mesh-alert.sh`.
4. **Maps:** copy an `.mbtiles` file into the maps storage shown in *Maps & GPS*; plug in a
   gpsd-supported GPS for your position.
5. **Library:** point *Library* at your ZIM/PDF/EPUB folders (for example Kiwix downloads you made earlier).
6. **Radio / APRS:** configure Direwolf yourself first. Transmit stays off until you enter your
   own licensed callsign and enable it.
7. **SDR Studio:** plug in an RTL-SDR; it only receives.

Nothing starts automatically and nothing transmits unless you choose to.
