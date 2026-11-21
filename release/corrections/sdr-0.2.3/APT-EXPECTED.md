# Expected apt -s output: task-sdr 0.2.3 on a clean Debian 13 trixie arm64 Pi (current recorded state: task-sdr 0.1.0)
**EXPECTED, not observed.** No Raspberry Pi was used. Derived from the OBSERVED private arm64 simulations in `apt-sim/` (real Debian 13 trixie / trixie-updates / trixie-security arm64 lists, synthetic installed states) and the real package control data. The Pi's own `./preflight.sh` output is the authority. The "N not upgraded" count depends on the Pi and is not predicted. Exact command run by preflight and install: `apt-get -s -o Debug::NoLocking=1 install --no-remove <debs>` (rollback adds `--allow-downgrades` for the rolled-back packages only).

task-sdr 0.2.3 has the same Depends as 0.2.2 (no new packages). It ships no dataset.

## Upgrade 0.1.0, 0.2.0, 0.2.1 or 0.2.2 → 0.2.3 (observed sims 02–05)
```
The following packages will be upgraded:
  task-sdr
1 upgraded, 0 newly installed, 0 to remove and N not upgraded.
Inst task-sdr [0.1.0] (0.2.3 local-deb [all])        # [0.2.0], [0.2.1] or [0.2.2] for the other paths
Conf task-sdr (0.2.3 local-deb [all])
```
If `librtlsdr0` is **not** already installed (normally it is, via soapysdr0.8-module-rtlsdr from 0.1.0), one more `Inst librtlsdr0 (2.0.2-2+b1 …[arm64])` line is expected.
**Never expected:** any `Remv`/`Purg` line, any downgrade, `E:`. Preflight FAILs if one appears.

## Rollback 0.2.3 → 0.2.2 / 0.2.1 / 0.2.0 (observed 06/07/08)
`Inst task-sdr [0.2.3] (0.2.x local-deb [all])` + `Conf`; preflight prints "rollback downgrade task-sdr 0.2.3 -> 0.2.x (explicitly requested)".

## Rollback 0.2.3 → 0.1.0 (observed 09)
On the Pi, SoapySDR from 0.1.0 is still installed (never autoremoved here), so expect only task-sdr's Inst + Conf. If SoapySDR was removed meanwhile, apt reinstalls it from the archive (about 40 packages), which needs network access or a mirror. Same-version `Inst X [v] (v …)` lines for Python 3.13 packages in the observed run are an artifact of the synthetic status file.

## Must fail (observed 10/11)
* An older task-sdr without the rollback allowance → "apt would DOWNGRADE task-sdr".
* python3-task-comms missing → `E: Unable to correct problems, you have held broken packages.`, exit 100.
