# T.A.S.K. Phase 4C — Communications 0.3.0: installation

**Status: development build. Installation on the Pi is NOT authorized yet.** These are the steps for when
Joshua approves. Nothing below starts a service automatically and nothing transmits.

Transfer: copy the zip to the Pi (USB stick, or Android → RaspController file manager), then
`unzip TASK-Phase4C-Communications-0.3.0.zip && cd TASK-Phase4C-Communications-0.3.0 && sha256sum -c SHA256SUMS`.

Order (each line can be done and tested separately):
```
# 0. dependencies — see DEPENDENCIES.md (bundled arm64 debs are a partial set; apt fetches the rest if online)
sudo apt install ./deps/arm64/*.deb            # optional, offline help only
# 1. shared lib + apps (no system services)
sudo apt install ./debs/python3-task-comms_0.3.0_all.deb ./debs/task-launcher_0.3.0_all.deb \
     ./debs/task-maps_0.1.1_all.deb ./debs/task-mesh_0.2.0_all.deb ./debs/rain-mesh_0.2.0_all.deb \
     ./debs/task-aprs_0.1.0_all.deb ./debs/task-sdr_0.1.0_all.deb ./debs/task-console_0.2.0_all.deb
# 2. core (files only; see MIGRATION.md before enabling anything)
sudo apt install ./debs/task-core_0.3.0_all.deb ./debs/task-core-compat_0.3.0_all.deb
```
Use `apt install ./file.deb` (not `dpkg -i`) so dependencies are resolved. Never `apt autoremove`.
Direwolf, gpsd and the radios are configured by Joshua; T.A.S.K. never writes their configuration.
