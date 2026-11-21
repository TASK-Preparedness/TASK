#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Build the Phase 4F debs: python3-task-comms 0.3.1, task-mesh 0.3.0, task-launcher 0.3.3 (Architecture: all).
Reuses the Phase 4C Pkg builder. argv only, no shell. Never enables any service.
Usage: build_phase4f.py OUTDIR [--mesh-repo /workspace/task-mesh]"""

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import build_release as br  # noqa: E402

REPO = br.REPO
WHEELS = ("meshtastic-2.7.11", "meshcore-2.3.15", "pycayennelpp-2.4.0", "pyserial_asyncio_fast-0.16")


def comms(out):
    p = br.Pkg("python3-task-comms", "0.3.1", br.PY, "T.A.S.K. shared communications helpers\n"
               " Status cards, task-geofeed/1, hash-chained audit, transmit policy (amateur + GMRS),\n"
               " APRS codec, notification store with per-protocol mesh sources. Pure Python, no hardware access.",
               "python")
    p.tree(REPO / "comms/task_comms", "usr/lib/python3/dist-packages/task_comms")
    p.docs(br.changelog("python3-task-comms", "0.3.1", [
        "Phase 4F: mesh.<protocol> notification sources (Meshtastic, MeshCore), badge_group(),",
        "  generic 'New Mesh Message' when locked, sound/sender options for desktop notifications.",
        "Documents that Meshtastic MeshPacket.priority is not sent over the air (BEL is the alert marker)."]),
        [REPO / "comms/docs/COMMS-STATUS.md", REPO / "comms/docs/GEOFEED.md", REPO / "comms/docs/NOTIFICATIONS.md"])
    return p.build(out)


def mesh(out, m, version="0.3.0", docs_glob=("docs/phase4f",)):
    br.run(["sha256sum", "-c", "SHA256SUMS"], cwd=m / "packaging/vendor", stdout=subprocess.DEVNULL)
    deps = [ln.strip().rstrip(",") for ln in (m / "packaging/debian/control").read_text().split("\nDepends:", 1)[1]
            .split("Recommends:")[0].splitlines() if ln.strip() and "${" not in ln]
    p = br.Pkg("task-mesh", version, ", ".join(deps + ["python3-task-comms (>= 0.3.1)"]),
               "T.A.S.K. Mesh Operations - Meshtastic and MeshCore field station\n"
               " One window for Meshtastic and MeshCore radios: all messages, per-protocol tabs, devices and\n"
               " network status; optional background receiver (systemd user unit, installed disabled).\n"
               " Bundles meshtastic 2.7.11 (GPL-3.0), meshcore 2.3.15 (MIT), pycayennelpp 2.4.0 (MIT) and\n"
               " pyserial-asyncio-fast 0.16 (BSD-3-Clause) under /usr/lib/task-mesh.", "hamradio",
               {"Recommends": "qt6-qpa-plugins, fonts-dejavu-core",
                "Suggests": "notification-daemon | xfce4-notifyd | dunst",
                "Provides": "rain-mesh", "Replaces": "rain-mesh (<< 0.2.0~)", "Breaks": "rain-mesh (<< 0.2.0~)"})
    lib = "usr/lib/task-mesh"
    p.tree(m / "task_mesh", f"{lib}/task_mesh")
    vend = p.path(f"{lib}/task_mesh/_vendor")
    for w in WHEELS:
        with zipfile.ZipFile(m / f"packaging/vendor/{w}-py3-none-any.whl") as z:
            z.extractall(vend)
    for junk in ("meshtastic/tests", "meshtastic/analysis", "meshtastic/.gitignore"):
        t = vend / junk
        if t.is_dir():
            shutil.rmtree(t)
        elif t.exists():
            t.unlink()
    p.file(m / "packaging/launcher/task-mesh", "usr/bin/task-mesh", 0o755)
    p.file(m / "packaging/launcher/task-mesh-service", "usr/bin/task-mesh-service", 0o755)
    if (m / "packaging/launcher/task-mesh-notify-setup").exists():
        p.file(m / "packaging/launcher/task-mesh-notify-setup", "usr/bin/task-mesh-notify-setup", 0o755)
    # user unit, shipped but NOT enabled: no [preset], no maintainer-script systemctl call
    p.file(m / "packaging/systemd/task-mesh-service.service", "usr/lib/systemd/user/task-mesh-service.service")
    p.file(m / "packaging/debian/task-mesh.desktop", "usr/share/applications/task-mesh.desktop")
    p.file(m / "packaging/debian/task-mesh.metainfo.xml", "usr/share/metainfo/task-mesh.metainfo.xml")
    p.file(m / "assets/icons/task-mesh.svg", "usr/share/icons/hicolor/scalable/apps/task-mesh.svg")
    for s in (48, 64, 128, 256):
        p.file(m / f"assets/icons/task-mesh-{s}.png", f"usr/share/icons/hicolor/{s}x{s}/apps/task-mesh.png")
    for s in ("postinst", "prerm"):
        body = (m / f"packaging/debian/task-mesh.{s}").read_text().replace("#DEBHELPER#\n", "")
        assert "systemctl" not in body and "deb-systemd" not in body, "maintainer scripts must not touch systemd"
        p.scripts[s] = body
    docs = [m / "README.md"] + [f for d in docs_glob for f in sorted((m / d).glob("*.md"))]
    p.docs((m / "packaging/debian/changelog").read_text(), docs)
    p.text("usr/share/doc/task-mesh/copyright", br.COPYRIGHT.format(pkg="task-mesh") + """
Files: usr/lib/task-mesh/task_mesh/_vendor/meshtastic/*
Copyright: Meshtastic contributors
License: GPL-3.0

Files: usr/lib/task-mesh/task_mesh/_vendor/meshcore/*
Copyright: 2025 Florent de Lamotte
License: MIT

Files: usr/lib/task-mesh/task_mesh/_vendor/cayennelpp/*
Copyright: pycayennelpp contributors
License: MIT

Files: usr/lib/task-mesh/task_mesh/_vendor/serial_asyncio_fast/*
Copyright: pyserial-asyncio-fast contributors
License: BSD-3-Clause

License: MIT
 Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
 associated documentation files (the "Software"), to deal in the Software without restriction ... (full
 text in each bundled *.dist-info/LICENSE file under /usr/lib/task-mesh/task_mesh/_vendor).
""")
    return p.build(out)


def launcher(out):
    br.run([sys.executable, str(REPO / "launcher/packaging/build_deb.py"), str(out), "--epoch", str(br.EPOCH)],
           stdout=subprocess.DEVNULL)
    return out / "task-launcher_0.3.3_all.deb"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--mesh-repo", default="/workspace/task-mesh")
    a = ap.parse_args()
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    for d in (comms(out), mesh(out, Path(a.mesh_repo)), launcher(out)):
        print(d.name)


if __name__ == "__main__":
    main()
