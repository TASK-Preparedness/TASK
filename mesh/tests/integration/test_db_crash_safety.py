# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""AT-15: SIGKILL a writer subprocess 20 times at random moments; the DB must always pass quick_check."""

import os
import random
import signal
import sqlite3
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHILD = textwrap.dedent("""
    import sys, time, itertools
    sys.path.insert(0, %r)
    from task_mesh.database.writer import DbWriter, OP_NODE, OP_OBS
    from task_mesh.domain.models import NodeRecord, Observation
    w = DbWriter(__import__("pathlib").Path(sys.argv[1]), batch_s=0.02)
    w.start(); w.wait_ready(10)
    print("ready", flush=True)
    for i in itertools.count():
        n = i %% 500
        w.submit(OP_NODE, NodeRecord(n + 1, 1790000000, 1790000000 + i, long_name="n%%d" %% n))
        w.submit(OP_OBS, Observation(n + 1, 1790000000 + i, rx_rssi=-90), None)
        if i %% 50 == 0:
            time.sleep(0.001)
""") % str(ROOT)


@pytest.mark.slow
@pytest.mark.timeout(240)
def test_at15_sigkill_loop_quick_check_ok(tmp_path):
    db = tmp_path / "crash.sqlite3"
    rng = random.Random(1234)
    counts = []
    env = {k: v for k, v in os.environ.items()}
    for _ in range(20):
        p = subprocess.Popen([sys.executable] + (["-S"] if sys.flags.no_site else []) + ["-c", CHILD, str(db)],
                             stdout=subprocess.PIPE, env=env)
        assert p.stdout.readline().strip() == b"ready"
        time.sleep(rng.uniform(0.05, 0.6))
        p.send_signal(signal.SIGKILL)
        p.wait(10)
        c = sqlite3.connect(db)
        assert c.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        counts.append(c.execute("SELECT count(*) FROM node_observations").fetchone()[0])
        c.close()
    assert counts == sorted(counts) and counts[-1] > 0
    from task_mesh.database.db import open_database

    r = open_database(db)
    from task_mesh.database.repo import load_nodes

    assert r.quarantined is None and len(load_nodes(r.conn)) > 0
    r.conn.close()
