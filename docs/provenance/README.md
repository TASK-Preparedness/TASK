# Provenance of locally modified sources

## Mesh notifier audible alert (task-mesh 0.3.1, hand-modified on the development Pi)

| File | Bytes | SHA-256 |
|---|---:|---|
| Pi `/usr/lib/task-mesh/task_mesh/hub/notifier.py` (modified) = `mesh/task_mesh/hub/notifier.py` here | 15,283 | `2864d2425cee7be738863139f4edb1a6d9fd83345693a5690503a46c933bbe1a` |
| Pi `notifier.py.pre-audio-backup` = task-mesh 0.3.1 source (`phase4f1` @ 8c9db14) | 14,636 | `3a8f61456d513096e48149bbc12ee7716499726f875324adb9ae0571c7620b72` |
| Pi `~/.local/share/task-mesh/sounds/mesh-alert.wav` (**not shipped**) | 1,176,590 | `2d57f69dd0f754c20d6ed6f861a3385435788a0598cb4049d776e0411b50b310` |

* `dpkg --verify task-mesh` on the Pi lists only `notifier.py` as changed.
* Diff: `mesh-notifier-audio.diff` (collected read-only on the Pi, 2026-11-08).
* The backup is kept in history only (via this provenance record); the maintained file is the modified one.
* Regeneration check on the build machine (2026-11-21): `scripts/generate-mesh-alert.sh`
  with sound-theme-freedesktop 0.8-6~deb13u1 (OGA SHA-256 `c28b4e0463eb3f19a3352049991c919cf8755e3f301f56a6276f5a81df472595`)
  and FFmpeg 7.1.5-0+deb13u1 produced a WAV of the **same length and header**
  (1,176,590 bytes) with 276 differing bytes in the audio samples (SHA-256
  `392b7d121db1eee07016360e253dd9580f79267778a54d409687c204c98dc500`). The Pi's FFmpeg
  version is unknown, so byte-identical reproduction is not claimed.
* Known, intentionally preserved behaviour: missing WAV is skipped silently; spawn errors
  are logged; simultaneous `paplay` children are not limited; path is literal
  `~/.local/share` (not `XDG_DATA_HOME`). Changes need a separate approved task-mesh release.

## R.A.I.N. → T.A.S.K. migration
`task_core_migrate/` and the task-core-compat package are byte-identical to what is
installed on the Pi (`/usr/lib/python3/dist-packages/task_core_migrate`,
`/usr/sbin/task-core-migrate`, `/usr/bin/rain-core-admin`). Preserved unchanged.

## Consolidation record
* Monorepo base: branch `phase5a-radio` @ `15f9862`, merged (no conflicts) with
  `phase4g-0.2.4` @ `6c01be7` (SDR 0.2.4) → staging merge `8149f25`.
* Mesh: separate repository branch `phase4f1` @ `8c9db14`, imported under `mesh/`.
* Firmware Manager design docs: branch `phase-fwmgr` @ `4daf1fc`, under `docs/design/firmware-manager/`.
* Every installed Python file of every T.A.S.K. package (task_core, task_core_migrate,
  task_comms, task_aprs, task_console, task_launcher, task_maps, task_resources, task_sdr,
  task_mesh except vendored wheels) was compared with this tree: 0 differences apart from the notifier.
  Launcher `apps.d`, task-core `modules`/`devices` manifests, both systemd units and the
  mesh launcher scripts are identical as well.
