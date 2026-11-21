# Expected apt -s output: task-launcher 0.3.6 + task-resources 0.2.3 on a clean Debian 13 trixie arm64 Pi (current state: launcher 0.3.4, resources 0.2.1)
**EXPECTED, not observed.** No Raspberry Pi was used. Derived from the OBSERVED private arm64 simulations in `apt-sim/` (real Debian 13 trixie / trixie-updates / trixie-security arm64 lists, synthetic installed states) and the real package control data. The Pi's own `./preflight.sh` output is the authority. The "N not upgraded" count depends on the Pi and is not predicted. Exact command run by preflight and install: `apt-get -s -o Debug::NoLocking=1 install --no-remove <debs>` (rollback adds `--allow-downgrades` for the rolled-back packages only).

## Upgrade from 0.3.4 + 0.2.1 (observed 01) or 0.3.5 + 0.2.2 (observed 02)
```
2 upgraded, 0 newly installed, 0 to remove and N not upgraded.
Inst task-launcher [0.3.4] (0.3.6 local-deb [all])
Inst task-resources [0.2.1] (0.2.3 local-deb [all])
Conf task-launcher (0.3.6 local-deb [all])
Conf task-resources (0.2.3 local-deb [all])
```
No new Debian dependencies: the Depends lines are unchanged from 0.3.5 / 0.2.2. No Remv/Purg, no downgrade.

## task-resources not installed yet (observed 03)
task-resources' Debian dependencies (python3-libzim 3.6.0-1.1+b1, libzim9, libxapian30, …) are added: about 48 extra Inst lines on the synthesised state; fewer on a Pi that already has some of them.

## Rollback (observed 04/05)
Two Inst [0.3.6]→0.3.5 / [0.2.3]→0.2.2 (or →0.3.4 / →0.2.1) + two Conf, each reported as "rollback downgrade … (explicitly requested)".

## Must fail (observed 06)
Older debs offered without the rollback allowance → "apt would DOWNGRADE".
