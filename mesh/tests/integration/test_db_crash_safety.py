# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""AT-15: SIGKILL a writer subprocess 20 times at random moments; the DB must always pass quick_check.

Clock (Milestone B fix): the child writer runs with a FROZEN retention clock (``now=lambda: REF``)
and writes observations stamped REF + i. Until 2026-11-21 the child used the real clock for its
startup retention prune but fixed timestamps from 1790000000 (2026-09-21 UTC); once the wall clock
passed REF + 30 days (about 2026-10-21) the 30-day ``node_observations`` prune at each restart
deleted earlier rows, so the row counts stopped being monotonic and the test failed. Mesh's
retention code is unchanged; only the test now controls its own reference time.
"""

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
REF = 1790000000  # fixed reference time (2026-09-21 UTC); data and the writer's clock both use it
CHILD = textwrap.dedent("""
    import sys, time, itertools
    sys.path.insert(0, %r)
    from task_mesh.database.writer import DbWriter, OP_NODE, OP_OBS
    from task_mesh.domain.models import NodeRecord, Observation
    REF = %d
    # frozen clock: the startup retention prune sees REF, so rows stamped REF + i are never pruned
    w = DbWriter(__import__("pathlib").Path(sys.argv[1]), batch_s=0.02, now=lambda: REF)
    w.start(); w.wait_ready(10)
    print("ready", flush=True)
    for i in itertools.count():
        n = i %% 500
        w.submit(OP_NODE, NodeRecord(n + 1, REF, REF + i, long_name="n%%d" %% n))
        w.submit(OP_OBS, Observation(n + 1, REF + i, rx_rssi=-90), None)
        if i %% 50 == 0:
            time.sleep(0.001)
""") % (str(ROOT), REF)


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

    r = open_database(db, now=REF)
    from task_mesh.database.repo import load_nodes

    assert r.quarantined is None and len(load_nodes(r.conn)) > 0
    r.conn.close()


def test_at15_clock_regression_retention_unchanged(tmp_path):
    """Documents the original AT-15 failure: rows stamped REF survive a prune at REF + 29 days and are
    deleted by the (unchanged) 30-day node_observations retention at REF + 31 days."""
    from task_mesh.core.config import RetentionConfig
    from task_mesh.database.db import open_database
    from task_mesh.database.writer import DbWriter, OP_NODE, OP_OBS
    from task_mesh.domain.models import NodeRecord, Observation
    from task_mesh.database import repo

    db = tmp_path / "clock.sqlite3"
    w = DbWriter(db, batch_s=0.01, now=lambda: REF)
    w.start()
    w.wait_ready(10)
    for i in range(10):
        w.submit(OP_NODE, NodeRecord(i + 1, REF, REF + i, long_name="n%d" % i))
        w.submit(OP_OBS, Observation(i + 1, REF + i, rx_rssi=-90), None)
    w.stop(10)
    day = 86400
    r = open_database(db, now=REF)
    try:
        count = lambda: r.conn.execute("SELECT count(*) FROM node_observations").fetchone()[0]  # noqa: E731
        assert count() == 10
        assert RetentionConfig().node_observations_days == 30
        repo.prune(r.conn, RetentionConfig(), REF + 29 * day)
        assert count() == 10
        repo.prune(r.conn, RetentionConfig(), REF + 31 * day)
        assert count() == 0
    finally:
        r.conn.close()
