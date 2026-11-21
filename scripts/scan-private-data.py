#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Scan a source tree for credentials, private data and machine-specific values.

    scripts/scan-private-data.py [ROOT] [--terms FILE] [--json]

--terms FILE: optional list of private strings (one per line: your callsign, device
MACs, serial numbers ...). Keep that file OUTSIDE the repository; matches are
reported by term number only, never echoed.
Exit status 1 when a HIGH finding exists.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HIGH = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY"),
    "aws-key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github-token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{40,}"),
    "slack-token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "google-api-key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "password-hash": re.compile(r"\$(?:argon2id?|2[aby]|6|5)\$[^\s\"']{20,}"),
}
MEDIUM = {
    "mac-address": re.compile(r"\b(?:[0-9A-F]{2}:){5}[0-9A-F]{2}\b", re.I),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "home-path": re.compile(r"/home/[a-z_][a-z0-9_-]*"),
    "private-ip": re.compile(r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"),
    "assigned-secret": re.compile(r"(?i)\b(?:password|passwd|secret|token|api_key|apikey)\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']"),
}
ALLOW_MAC = {"00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff", "xx:xx:xx:xx:xx:xx"}
ALLOW_EMAIL_DOMAINS = ("example.com", "example.org", "example.invalid", "invalid", "users.noreply.github.com")
SKIP_DIRS = {".git", "__pycache__", "node_modules"}
SKIP_SUFFIX = {".png", ".jpg", ".whl", ".svg", ".ico", ".gz", ".zip", ".deb"}
# reviewed templates that legitimately share a forbidden name (no secrets inside)
ALLOW_FILES = {"deploy/auth.toml"}
FORBIDDEN_FILES = {"radio-protocols.json", "auth.toml", "sessions.toml", "amateur.toml", "gmrs.toml", "mesh-alert.wav"}


def scan(root: Path, terms: list[str]):
    findings = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or SKIP_DIRS & set(p.relative_to(root).parts):
            continue
        rel = str(p.relative_to(root))
        if p.name in FORBIDDEN_FILES and not any(rel == a or rel.endswith("/" + a) for a in ALLOW_FILES):
            findings.append(("HIGH", "forbidden-file", rel, 0, p.name))
        if p.suffix.lower() in SKIP_SUFFIX or p.name.endswith((".sqlite", ".sqlite3")):
            if p.name.endswith((".sqlite", ".sqlite3")):
                findings.append(("HIGH", "database-file", rel, 0, p.name))
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for name, rx in HIGH.items():
                if rx.search(line):
                    findings.append(("HIGH", name, rel, n, ""))
            for name, rx in MEDIUM.items():
                for m in rx.finditer(line):
                    v = m.group(0)
                    if name == "mac-address" and v.lower() in ALLOW_MAC:
                        continue
                    if name == "email" and v.lower().endswith(ALLOW_EMAIL_DOMAINS):
                        continue
                    findings.append(("MEDIUM", name, rel, n, v))
            low = line.lower()
            for i, t in enumerate(terms, 1):
                if t and t.lower() in low:
                    findings.append(("HIGH", f"private-term-{i}", rel, n, "<redacted>"))
    return findings


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--terms")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    terms = [t.strip() for t in Path(a.terms).read_text().splitlines()] if a.terms else []
    f = scan(Path(a.root), [t for t in terms if t])
    if a.json:
        print(json.dumps([dict(zip(("severity", "kind", "file", "line", "value"), x)) for x in f], indent=1))
    else:
        for sev, kind, rel, n, v in f:
            print(f"{sev:6} {kind:18} {rel}:{n} {v}")
        print(f"summary: {sum(1 for x in f if x[0] == 'HIGH')} HIGH, {sum(1 for x in f if x[0] == 'MEDIUM')} MEDIUM")
    return 1 if any(x[0] == "HIGH" for x in f) else 0


if __name__ == "__main__":
    sys.exit(main())
