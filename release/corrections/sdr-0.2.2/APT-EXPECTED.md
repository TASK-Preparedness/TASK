# Expected apt -s output: task-sdr 0.2.2 on a clean Debian 13 trixie arm64 Pi (current recorded state: task-sdr 0.1.0)
**EXPECTED, not observed.** No Raspberry Pi was used. Derived from the OBSERVED private arm64 simulations in `apt-sim/` (real Debian 13 trixie / trixie-updates / trixie-security arm64 lists, synthetic installed states) and the real package control data. The Pi's own `./preflight.sh` output is the authority. The "N not upgraded" count depends on the Pi and is not predicted. Exact command run by preflight and install: `apt-get -s -o Debug::NoLocking=1 install --no-remove <debs>` (rollback adds `--allow-downgrades` for the rolled-back packages only).

## Upgrade 0.1.0, 0.2.0 or 0.2.1 → 0.2.2 (observed sims 02/03/04)
```
The following packages will be upgraded:
  task-sdr
1 upgraded, 0 newly installed, 0 to remove and N not upgraded.
Inst task-sdr [0.1.0] (0.2.2 local-deb [all])        # [0.2.0] or [0.2.1] for the other paths
Conf task-sdr (0.2.2 local-deb [all])
```
If `librtlsdr0` is **not** already installed (it normally is, through soapysdr0.8-module-rtlsdr from 0.1.0), one more line is expected:
`Inst librtlsdr0 (2.0.2-2+b1 Debian:13.x/stable [arm64])` (version from the real trixie arm64 list).
**Never expected:** any `Remv`/`Purg` line (SoapySDR stays installed; `--no-remove`), any downgrade, `E:`. Preflight FAILs if one appears.

## Rollback 0.2.2 → 0.2.1 / 0.2.0 (observed 05/06)
`Inst task-sdr [0.2.2] (0.2.1 local-deb [all])` + `Conf`; preflight prints "rollback downgrade task-sdr 0.2.2 -> 0.2.1 (explicitly requested)".

## Rollback 0.2.2 → 0.1.0 (observed 07)
On the Pi, SoapySDR from 0.1.0 is still installed (never autoremoved here), so expect one Inst + one Conf for task-sdr only.
If SoapySDR was removed meanwhile, apt reinstalls it from the archive (observed: 39 extra Inst lines incl. python3-soapysdr 0.8.1-5+b2 and soapysdr0.8-module-all 0.8.1-5+b2), which needs network or a mirror.
In that observed run, a few Python 3.13 packages appear as `Inst X [3.13.5-2+deb13u5] (3.13.5-2+deb13u5 …)` with the same version on both sides. This is an artifact of the synthesised status file, not a downgrade, and is not expected on a Pi.

## Must fail (observed 08/09)
* Installing an older task-sdr without the rollback allowance → "apt would DOWNGRADE task-sdr".
* python3-task-comms missing (it is not in Debian) → `E: Unable to correct problems, you have held broken packages.`, exit 100.
