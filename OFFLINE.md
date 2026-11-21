# Offline installation and use

Offline operation is a core design rule: every module works without internet once
installed, using data you provide.

## Three kinds of installation

| Kind | What it means | Status |
|---|---|---|
| **Fully offline** | Everything needed (T.A.S.K. `.deb`s *and* every Debian dependency) is in a downloaded bundle; apt runs with `--no-download` and fails rather than fetching. | Planned — bundle not built yet |
| **Needs additional downloads** | T.A.S.K. packages are local, but Debian dependencies (Qt, numpy, Direwolf…) come from your normal apt sources. | Planned |
| **Optional online features** | Map tile downloads (subject to each source's policy) and similar features. Never automatic. | Implemented in Maps (opt-in) |

The installer always shows which kind applies before doing anything and never
downloads silently.

## Offline bundle (planned: TASK-RaspberryPi-Offline-Bundle)

* Target: Debian 13 trixie **arm64** only.
* Contents: validated T.A.S.K. `.deb`s, the exact Debian dependency `.deb`s resolved
  on a clean trixie arm64 system (all DFSG-free, redistributable with their
  copyright files), a local apt repository index, `SHA256SUMS`, manifest and license notices.
* Not included (you supply them): maps (MBTiles), ZIM libraries, medical references,
  radio firmware, the CC-BY-SA mesh alert sound (generate it with `scripts/generate-mesh-alert.sh`).
* Size target: each download part under 25 MB where feasible (the Phase 4C dependency set
  alone was ~25 MB split in two parts), so a full bundle will be several parts.

## Why it is not built yet

Building it correctly needs a **clean Debian 13 arm64 system or chroot** to resolve
the exact dependency closure, and validated T.A.S.K. packages to put in it. The
build machine used so far is x86_64; cross-resolving is possible but must be
validated on arm64 before release.

## Offline content you may want

* Kiwix ZIM files (Wikipedia, WikiMed, etc.) — download from Kiwix while online; their licenses vary per file.
* MBTiles maps you are permitted to store offline (e.g. self-rendered OpenStreetMap data, ODbL).
* USGS topo data is public domain in the US; check each source.
