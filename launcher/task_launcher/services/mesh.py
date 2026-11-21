# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""T.A.S.K. Mesh Operations (task-mesh) detection, read-only.

task-mesh 0.2.0: console script ``task-mesh`` → ``task_mesh.app:main``; its Debian package installs
``/usr/bin/task-mesh`` (a /bin/sh wrapper) and the modules under ``/usr/lib/task-mesh``. The legacy
rain-mesh 0.1.0 (``/usr/bin/rain-mesh``, ``/usr/lib/rain-mesh/rain_mesh``) is still detected. CLI: ``--version``, ``--debug``, ``--no-autoconnect``,
``--forget-user-data``. It opens the Meshtastic USB serial port itself (vendored meshtastic
SerialInterface) and does not use task-core.

The ``meshtastic`` CLI alone is reported but never counts as the Mesh app.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from task_launcher.services import probe

CANDIDATES = ("/usr/bin/task-mesh", "/usr/local/bin/task-mesh", "/usr/bin/rain-mesh", "/usr/local/bin/rain-mesh")
DPKG_STATUS = Path("/var/lib/dpkg/status")


@dataclass
class MeshStatus:
    executable: str = ""
    package_version: str = ""
    module_dir: str = ""
    meshtastic_cli: str = ""
    running: list = field(default_factory=list)
    cli_running: list = field(default_factory=list)   # meshtastic CLI processes (serial conflict)
    serial_ports: list = field(default_factory=list)

    def summary(self):
        if self.executable:
            v = f" {self.package_version}" if self.package_version else ""
            return f"task-mesh{v} installed" + (" · running" if self.running else "")
        extra = " (meshtastic CLI present, not a substitute)" if self.meshtastic_cli else ""
        return "task-mesh not installed" + extra


def dpkg_version(package: str, status_file: Path = DPKG_STATUS) -> str:
    """Installed version from the dpkg status database (read-only)."""
    try:
        text = status_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for block in text.split("\n\n"):
        if re.search(rf"^Package: {re.escape(package)}$", block, re.M) and \
                re.search(r"^Status: install ok installed$", block, re.M):
            m = re.search(r"^Version: (\S+)$", block, re.M)
            return m.group(1) if m else ""
    return ""


def serial_ports(by_id=Path("/dev/serial/by-id")):
    """Names under /dev/serial/by-id (listing only; nothing is opened)."""
    try:
        return sorted(os.listdir(by_id))
    except OSError:
        return []


def collect(candidates=CANDIDATES, status_file=DPKG_STATUS, procs_fn=None, ports_fn=serial_ports):
    st = MeshStatus()
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            st.executable = c
            break
    st.package_version = dpkg_version("task-mesh", status_file)
    for mod_dir, pkg in (("/usr/lib/task-mesh", "task_mesh"), ("/usr/lib/rain-mesh", "rain_mesh")):
        if os.path.isdir(f"{mod_dir}/{pkg}"):
            st.module_dir = mod_dir
            break
    if not st.package_version:
        st.package_version = dpkg_version("rain-mesh", status_file)
    st.meshtastic_cli = probe.find_program(["meshtastic"]).get("meshtastic", "")
    procs = (procs_fn or (lambda: probe.processes(["task-mesh", "rain-mesh", "python3", "python", "meshtastic"])))()
    st.running = [p for p in procs if any("rain_mesh" in a or "task_mesh" in a or a.endswith(("task-mesh", "rain-mesh")) for a in p.argv)]
    st.cli_running = [p for p in procs if p not in st.running and
                      any(a == "meshtastic" or a.endswith("/meshtastic") for a in p.argv[:2])]
    st.serial_ports = ports_fn()
    return st
