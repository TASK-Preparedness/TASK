# Expected apt -s output: task-sdr 0.2.0 (r2) on a clean Debian 13 trixie arm64 Pi (current state: task-sdr 0.1.0)
**EXPECTED, not observed.** No Raspberry Pi was used. Derived from the OBSERVED private arm64 simulations in `apt-sim/` (real Debian 13 trixie / trixie-updates / trixie-security arm64 lists, synthetic installed states) and the real package control data. The Pi's own `./preflight.sh` output is the authority. The "N not upgraded" count depends on the Pi and is not predicted. Exact command run by preflight and install: `apt-get -s -o Debug::NoLocking=1 install --no-remove <debs>` (rollback adds `--allow-downgrades` for the rolled-back packages only).

## Upgrade 0.1.0 → 0.2.0 (observed 02)
```
1 upgraded, 0 newly installed, 0 to remove and N not upgraded.
Inst task-sdr [0.1.0] (0.2.0 local-deb [all])
Conf task-sdr (0.2.0 local-deb [all])
```
Plus `Inst librtlsdr0 (2.0.2-2+b1 …)` only if librtlsdr0 is absent. No Remv/Purg, no downgrade.

## Rollback 0.2.0 → 0.1.0 (observed 03)
task-sdr only while SoapySDR is installed (the normal case); otherwise about 39 SoapySDR-related packages from the archive.

## Must fail (observed 04)
task-sdr 0.2.1 or 0.2.2 installed → preflight FAILs ("newer than 0.2.0: refusing to downgrade").
