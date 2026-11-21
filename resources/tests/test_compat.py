# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Compatibility and boundaries: no Kiwix, no HTTP server, no network, no Core socket, no root,
GPL headers. Source-level checks over the shipped package."""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "task_resources"
FORBIDDEN_IMPORTS = {"subprocess", "socket", "http", "urllib.request", "requests", "socketserver",
                     "task_core", "task_launcher", "ssl", "ftplib"}


def sources():
    return sorted(PKG.rglob("*.py"))


def test_no_network_server_kiwix_or_core_imports():
    """Phase 4E: network code is allowed ONLY in task_resources/net/safehttp.py (the SSRF-safe client)."""
    bad = []
    for p in sources():
        if p.name == "safehttp.py" and p.parent.name == "net":
            continue
        tree = ast.parse(p.read_text())
        for n in ast.walk(tree):
            names = [a.name for a in n.names] if isinstance(n, ast.Import) else                 [n.module or ""] if isinstance(n, ast.ImportFrom) else []
            for m in names:
                if m in FORBIDDEN_IMPORTS or m.split(".")[0] in {"subprocess", "socket", "http", "requests", "ssl"}:
                    bad.append((p.name, m))
    assert bad == []
    text = "\n".join(p.read_text() for p in sources())
    for word in ("kiwix-serve", "QNetworkAccessManager", "shell=True", "os.system", "/run/task/core.sock"):
        assert word not in text, word


def test_spdx_headers():
    for p in list(sources()) + sorted((PKG.parent / "tests").glob("*.py")):
        lines = p.read_text().splitlines()[:2]
        assert lines == ["# SPDX-License-Identifier: GPL-3.0-or-later",
                         "# SPDX-FileCopyrightText: 2026 Joshua Sturtz"], p


def test_refuses_root_and_prints_version(monkeypatch, capsys):
    from task_resources import app
    assert app.main(["--version"]) == 0 and "task-resources 0.2.4" in capsys.readouterr().out
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    assert app.main(["--no-scan"]) == 2


def test_app_module_starts_without_display_dependencies_on_import():
    r = subprocess.run([sys.executable, "-c", "import task_resources.app, task_resources.index, "
                        "task_resources.discovery"], env=dict(os.environ, PYTHONPATH=str(PKG.parent) + ":" +
                                                               os.environ.get("PYTHONPATH", "")),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_default_settings_only_read_kiwix_locations():
    from task_resources.settings import Settings
    s = Settings()
    assert s.scan_dirs == ["/library/zims/content", "/library/working/zims"]
    assert s.library_xml == ["/library/zims/library.xml"] and s.viewer == "auto"
    assert s.managed_root == "~/.local/share/task-resources/downloads"
