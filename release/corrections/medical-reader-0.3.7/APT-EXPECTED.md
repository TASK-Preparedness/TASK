# Expected apt -s output: task-launcher 0.3.7 + task-resources 0.2.4 on Debian 13 trixie arm64 (Pi)
**EXPECTED, not observed.** No Raspberry Pi was used. Derived from the OBSERVED private arm64 simulations in `apt-sim/` (real Debian 13 trixie / trixie-updates / trixie-security arm64 lists, synthetic installed states) and the real package control data. The Pi's own `./preflight.sh` output is the authority. Exact command: `apt-get -s -o Debug::NoLocking=1 install --no-remove <debs>` (rollback adds `--allow-downgrades` for the rolled-back packages only).

## Upgrade from 0.3.6 + 0.2.3 (observed 01) or 0.3.4 + 0.2.1 (observed 02)
```
2 upgraded, 0 newly installed, 0 to remove and N not upgraded.
Inst task-launcher [0.3.6] (0.3.7 local-deb [all])
Inst task-resources [0.2.3] (0.2.4 local-deb [all])
Conf task-launcher (0.3.7 local-deb [all])
Conf task-resources (0.2.4 local-deb [all])
```
No new Debian dependencies (Depends unchanged). The optional image plugins (`qt6-image-formats-plugins`, `qt6-svg-plugins`) are NOT pulled in.

## task-resources not installed yet (observed 03)
python3-libzim, libzim9, libxapian30 etc. are added: about 48 extra Inst lines on the synthesised state.

## Rollback (observed 04/05)
Two Inst [0.3.7]→0.3.6 / [0.2.4]→0.2.3 (or →0.3.4 / →0.2.1) + two Conf, "explicitly requested" downgrades.

## Must fail (observed 06)
Older debs without the rollback allowance → "apt would DOWNGRADE".
