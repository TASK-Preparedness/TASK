#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Consistent single-file backup of a WAL SQLite database (db + -wal + -shm treated as one set), without
creating or deleting anything beside the source. Uses rosnap.py (a copy of task_resources/rosnap.py).
usage: sqlite_backup.py SRC DST    -> prints the mode used (snapshot|live); exit 1 on failure
       sqlite_backup.py --check SRC -> backs up into a private temp dir, runs PRAGMA integrity_check on the
                                       COPY, prints "<mode> <result>", removes only that temp dir. Read-only."""
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rosnap  # noqa: E402


def check(src):
    with tempfile.TemporaryDirectory(prefix="task-dbcheck-") as d:
        dst = Path(d) / "copy.sqlite"
        mode = rosnap.consistent_backup(src, dst)
        c = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)
        try:
            res = c.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            c.close()
    return f"{mode} {res}", res == "ok"


if __name__ == "__main__":
    try:
        if sys.argv[1] == "--check":
            text, ok = check(sys.argv[2])
            print(text)
            sys.exit(0 if ok else 1)
        print(rosnap.consistent_backup(sys.argv[1], sys.argv[2]))
    except Exception as exc:  # noqa: BLE001
        print(f"backup failed: {exc}", file=sys.stderr)
        sys.exit(1)
