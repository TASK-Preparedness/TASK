<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Working Mesh audio preservation and licensing — task-mesh 0.3.2 plan
The installed Pi notifier is authoritative; this review does not overwrite it or edit the Mesh worktree. task-mesh 0.3.2 remains a separate, approved future release, not part of Radio installation.

## Verified bytes and diff
Recomputed directly from extracted bytes and matched `inventory/important-sha256.txt:1-3`:

| File | Bytes | SHA-256 |
|---|---:|---|
| `/usr/lib/task-mesh/task_mesh/hub/notifier.py` | 15,283 | `2864d2425cee7be738863139f4edb1a6d9fd83345693a5690503a46c933bbe1a` |
| `/usr/lib/task-mesh/task_mesh/hub/notifier.py.pre-audio-backup` | 14,636 | `3a8f61456d513096e48149bbc12ee7716499726f875324adb9ae0571c7620b72` |
| `/home/<user>/.local/share/task-mesh/sounds/mesh-alert.wav` | 1,176,590 | `2d57f69dd0f754c20d6ed6f861a3385435788a0598cb4049d776e0411b50b310` |

`inventory/notifier-audio.diff:1-41` records two intentional changes: format_notification now always sets suppress-sound=True; NotificationManager.handle starts direct audio after existing filters. Source `/usr/lib/task-mesh/task_mesh/hub/notifier.py:214-219,260-306` confirms this. Full `diff` command exits 1 because differences exist; not a collection error. Recomputed unified diff hunks match the supplied diff after ignoring its final extra empty diagnostic line (headers contain collection timestamps). `inventory/verify-task-mesh.txt:4` identifies only notifier.py as modified; all other supplied package verification reports have no listed mismatch.

Dedup/history check precedes settings mute/quiet/focus checks (`notifier.py:263-279`). Asynchronous `subprocess.Popen` uses argv list `/usr/bin/paplay`, explicit WAV path, DEVNULL streams, start_new_session=True, close_fds=True (`:291-306`). Sound setting false skips playback while suppress-sound remains true. Locked/unknown state affects notification disclosure (`:282-290`, `format_notification:214-235`), not an invented unlock. Existing real incoming-message audibility was reported verified by Joshua; no hardware replay was performed in this review.

Limitations to retain honestly: missing WAV is skipped; absent paplay/spawn exception is logged and desktop sender still runs; asynchronous nonzero exit isn't monitored. Existing code neither blocks nor limits simultaneous paplay children. It uses literal ~/.local/share, not XDG_DATA_HOME. Do not silently 'improve' these in the preservation release; add tests and propose any behavior change separately. Loud gain may be unsuitable with headphones: keep user sound/quiet controls, do not auto-raise system volume.

## Exact Joshua transformation recipe
Recorded as supplied; **not executed during this review**:

```bash
ffmpeg -hide_banner -loglevel error -n \
  -i /usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga \
  -af "volume=26dB,alimiter=limit=0.95" \
  -c:a pcm_s16le \
  ~/.local/share/task-mesh/sounds/mesh-alert.wav
```

Source package on Pi: sound-theme-freedesktop 0.8-6~deb13u1 (`inventory/versions.txt:10`), ffmpeg version not included. The recipe records intended +26dB/0.95 processing; filters/tool versions may affect byte reproducibility, so do not regenerate over the verified WAV. Future provenance collection may record FFmpeg version and original OGA hash; archive did not include original OGA, so its byte equivalence with upstream release cannot be independently proven here.

## Upstream attribution — resolved per-file, with version nuance
Opened public upstream release source on 2026-11-08 EST:
https://people.freedesktop.org/~mccann/dist/sound-theme-freedesktop-0.8.tar.bz2

Downloaded release SHA-256 `cb518b20eef05ec2e82dda1fa89a292c1760dc023aba91b8aa69bafac85e8a14`.
Its `sound-theme-freedesktop-0.8/README:3-4` directs licensing/origins to CREDITS.
Exact CREDITS lines 1–4:

```text
alarm-clock-elapsed
        Copyright: Tim/corsica_s
        URL: http://www.freesound.org/samplesViewSingle.php?id=67091
        License: CC-BY-SA (relicensed with permission from author)
```

CREDITS SHA-256 `ed8cd7965340940551f37ef96b32aaa7d76b677c30fb912412ddb50bc02e0dc3`.
This pins the author and ShareAlike license **for this sound**, unlike blanket multi-license metadata. Upstream CREDITS itself does not specify the version number. Debian's historical **per-file** copyright mapping supplies the explicit version, opened this turn:
https://tracker.debian.org/media/packages/s/sound-theme-freedesktop/copyright-0.8-2
Exact text:

```text
Files: stereo/alarm-clock-elapsed.oga
Copyright: Tim/corsica_s
License: CC-BY-SA-3.0
```

The same Debian copyright contains the full Creative Commons Attribution-ShareAlike 3.0 Unported terms. Its section 3(b) requires clearly identifying alterations; 4(b) allows redistribution of adaptations under the specified ShareAlike conditions; 4(c) requires author/pseudonym, supplied title/source URI and adaptation credit. License URI: https://creativecommons.org/licenses/by-sa/3.0/ (legal text: /legalcode).

Finding: **use CC-BY-SA-3.0 for the derived WAV**, attribute Tim/corsica_s and label Joshua's modification. Upstream exact credit is confirmed; version is supported by Debian's explicit per-file mapping, not claimed as a version written in upstream CREDITS. Current installed package copyright is aggregate; that does not overturn the upstream per-file attribution. Debian sources fetch failed, GitLab raw blocked; original freedesktop release was fetched successfully, so these failures were not treated as evidence of missing licensing.

This is suitable for redistribution as a separately licensed asset in a free/open-source application, with obligations honored. Do not relabel the WAV GPL, imply author endorsement, or assume the whole theme's GPL licenses govern this one file. Keep code GPL-3.0-or-later and this sound's license distinct in a collection. Preserve source/credits and full license offline in packaging.

### Proposed packaged attribution text
“mesh-alert.wav is adapted from alarm-clock-elapsed.oga in sound-theme-freedesktop 0.8, copyright Tim/corsica_s, original source http://www.freesound.org/samplesViewSingle.php?id=67091 (relicensed to CC-BY-SA with the author's permission as recorded in upstream CREDITS). This adaptation by Joshua Sturtz applies +26 dB gain, alimiter limit=0.95 and PCM signed 16-bit WAV conversion using the recipe above. Distributed under Creative Commons Attribution-ShareAlike 3.0 Unported, https://creativecommons.org/licenses/by-sa/3.0/. No endorsement implied.”

Ship per-file stanza for the default sound in `debian/copyright`, full CC-BY-SA-3.0 text, original upstream CREDITS and transformation README under `/usr/share/doc/task-mesh/`. Default optional packaged asset location `/usr/share/task-mesh/sounds/mesh-alert.wav` is a **proposal**; current working code reads only user's path. Introducing fallback requires separate code review/tests. Packages must never write, replace or delete ~/.local/share/task-mesh/sounds/mesh-alert.wav. No WAV or upstream source archive is included in this docs ZIP.

## 0.3.2 preservation/release steps (future authorization)
1. Copy the authoritative installed notifier bytes into canonical Mesh source only when approved, keeping exact current behavior and attribution. Diff against pre-audio backup as audit record; never use old workspace copy as master.
2. Baseline tests cover every filter plus exact Popen and suppress-sound arguments; negative tests in TEST-PLAN. Keep Mesh notifications/privacy, hub store and existing ownership behavior unchanged.
3. New release version task-mesh 0.3.2; maintain full existing Depends after obtaining installed metadata, add paplay dependency; do not regenerate or alter the verified user WAV. Distribution default licensed as above only after provenance/package review.
4. Pre-unpack modified-file guard checks known notifier hash and refuses unknown edits/downgrades; private snapshot includes authoritative notifier, backup, asset and user settings. No service restart/enablement in maintainer scripts.
5. Install/restart/real-message retest each require explicit later approval. Rollback must preserve this patch, not restore stock 0.3.1 or the pre-audio backup. See PACKAGING-AND-ROLLBACK.md.
