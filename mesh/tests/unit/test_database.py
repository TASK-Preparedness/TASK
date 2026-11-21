# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""DB open/migrations/quarantine/backup/refuse-newer (AT-16, AT-17), retention (AT-18), writer, persistence."""

import os
import shutil
import sqlite3

import pytest

from task_mesh.core.config import RetentionConfig
from task_mesh.database import repo
from task_mesh.database.db import (
    DatabaseError,
    SchemaTooNewError,
    load_migrations,
    migrate,
    open_database,
)
from task_mesh.database.writer import OP_CONN_EVENT, OP_NODE, OP_OBS, OP_RADIO, OP_RADIO_EVENT, DbWriter
from task_mesh.domain.models import (
    ConnectionEventRecord,
    EventLevel,
    NodeRecord,
    Observation,
    PortCandidate,
    RadioEvent,
    RadioIdentity,
    Source,
)

NOW = 1790000000


def test_fresh_db_pragmas_and_schema(tmp_path):
    r = open_database(tmp_path / "d" / "x.sqlite3", NOW)
    c = r.conn
    assert r.applied == [1] and r.schema_version == 1 and r.quarantined is None
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert c.execute("PRAGMA auto_vacuum").fetchone()[0] == 2  # INCREMENTAL
    assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert c.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
    assert c.execute("SELECT version, name FROM schema_migrations").fetchall() == [(1, "initial")]
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"radios", "nodes", "node_observations", "connection_events", "radio_events"} <= tables
    c.close()


def test_migrator_idempotent(tmp_path):
    p = tmp_path / "x.sqlite3"
    open_database(p, NOW).conn.close()
    r = open_database(p, NOW + 1)
    assert r.applied == [] and r.backups == [] and r.schema_version == 1
    assert r.conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 1
    r.conn.close()


def test_backup_taken_before_new_migration(tmp_path):
    p = tmp_path / "x.sqlite3"
    open_database(p, NOW).conn.close()
    mdir = tmp_path / "migs"
    shutil.copytree(os.path.dirname(repo.__file__) + "/migrations", mdir)
    (mdir / "0002_extra.sql").write_text("CREATE TABLE extra (id INTEGER PRIMARY KEY) STRICT;\n")
    r = open_database(p, NOW, migrations=load_migrations(mdir))
    assert r.applied == [2] and r.schema_version == 2
    bak = tmp_path / "x.sqlite3.pre-v0002.bak"
    assert r.backups == [bak] and bak.exists()
    assert sqlite3.connect(bak).execute("PRAGMA user_version").fetchone()[0] == 1
    r.conn.close()


def test_newer_schema_refused(tmp_path):
    p = tmp_path / "x.sqlite3"
    r = open_database(p, NOW)
    r.conn.execute("PRAGMA user_version = 99")
    r.conn.close()
    with pytest.raises(SchemaTooNewError, match="newer"):
        open_database(p, NOW)


def test_checksum_mismatch_refused(tmp_path):
    p = tmp_path / "x.sqlite3"
    r = open_database(p, NOW)
    r.conn.execute("UPDATE schema_migrations SET checksum = 'tampered'")
    r.conn.close()
    with pytest.raises(DatabaseError, match="checksum"):
        open_database(p, NOW)


def test_corrupt_db_quarantined_not_deleted(tmp_path):
    p = tmp_path / "x.sqlite3"
    junk = os.urandom(8192)
    p.write_bytes(junk)
    r = open_database(p, NOW)
    assert r.quarantined is not None and r.quarantined.name.startswith("x.sqlite3.corrupt-")
    assert r.quarantined.read_bytes() == junk
    assert r.schema_version == 1
    r.conn.close()


def test_migration_failure_rolls_back(tmp_path):
    mdir = tmp_path / "migs"
    shutil.copytree(os.path.dirname(repo.__file__) + "/migrations", mdir)
    (mdir / "0002_broken.sql").write_text("CREATE TABLE ok1 (a INTEGER) STRICT;\nTHIS IS NOT SQL;\n")
    c = sqlite3.connect(tmp_path / "x.sqlite3", isolation_level=None)
    migrate(c, None, NOW, load_migrations(mdir)[:1])
    with pytest.raises(DatabaseError):
        migrate(c, None, NOW, load_migrations(mdir))
    assert c.execute("PRAGMA user_version").fetchone()[0] == 1
    assert c.execute("SELECT count(*) FROM sqlite_master WHERE name='ok1'").fetchone()[0] == 0


def _seed(conn):
    repo.upsert_radio(conn, RadioIdentity(5, "!00000005"), PortCandidate("/dev/ttyUSB0"), NOW)
    repo.upsert_node(conn, NodeRecord(7, NOW - 10, NOW, long_name="A", heard_via_radio=5,
                                      snr=1.5, snr_source=Source.PACKET, is_licensed=False))


def test_repo_roundtrip_preserves_values_and_first_seen(tmp_path):
    r = open_database(tmp_path / "x.sqlite3", NOW)
    _seed(r.conn)
    repo.upsert_node(r.conn, NodeRecord(7, NOW + 500, NOW + 1, long_name="B", heard_via_radio=999))
    nodes = repo.load_nodes(r.conn)
    assert len(nodes) == 1
    n = nodes[0]
    assert n.long_name == "B" and n.first_seen_local == NOW - 10 and n.stale
    assert n.heard_via_radio is None  # unknown radio -> NULL instead of FK failure
    assert n.rssi_last is None and n.battery_level is None


def test_observation_for_unknown_node_skipped(tmp_path):
    r = open_database(tmp_path / "x.sqlite3", NOW)
    _seed(r.conn)
    repo.insert_observation(r.conn, Observation(7, NOW, rx_rssi=-90), 5)
    repo.insert_observation(r.conn, Observation(8, NOW, rx_rssi=-90), 5)
    assert r.conn.execute("SELECT node_num, rx_rssi FROM node_observations").fetchall() == [(7, -90)]


def test_retention_prunes_old_rows_keeps_nodes(tmp_path):
    r = open_database(tmp_path / "x.sqlite3", NOW)
    _seed(r.conn)
    for age_days in (0, 2, 5):
        repo.insert_observation(r.conn, Observation(7, NOW - age_days * 86400), 5)
        repo.insert_connection_event(r.conn, ConnectionEventRecord(NOW - age_days * 86400, "A", "B"))
        repo.insert_radio_event(r.conn, RadioEvent(NOW - age_days * 86400, EventLevel.INFO, "k", "m"), 5)
    out = repo.prune(r.conn, RetentionConfig(node_observations_days=1, connection_events_days=3,
                                             radio_events_days=1, radio_events_max_rows=1), NOW, chunk=1)
    assert out["node_observations"] == 2 and out["connection_events"] == 1
    assert r.conn.execute("SELECT count(*) FROM node_observations").fetchone()[0] == 1
    assert r.conn.execute("SELECT count(*) FROM radio_events").fetchone()[0] == 1
    assert r.conn.execute("SELECT count(*) FROM nodes").fetchone()[0] == 1


def test_radio_event_detail_json_valid(tmp_path):
    r = open_database(tmp_path / "x.sqlite3", NOW)
    repo.insert_radio_event(r.conn, RadioEvent(NOW, EventLevel.WARNING, "bad_packet", "m", {"error": "X"}), None)
    assert r.conn.execute("SELECT json_extract(detail_json, '$.error') FROM radio_events").fetchone()[0] == "X"


def test_writer_end_to_end_and_reload(tmp_path):
    p = tmp_path / "w.sqlite3"
    w = DbWriter(p, now=lambda: NOW)
    w.start()
    assert w.wait_ready(5) and w.stats().status == "ok"
    w.submit(OP_RADIO, RadioIdentity(5, "!00000005"), PortCandidate("/dev/ttyUSB0"), NOW)
    for i in range(500):
        w.submit(OP_NODE, NodeRecord(100 + i % 50, NOW, NOW, long_name=f"n{i % 50}", heard_via_radio=5))
        w.submit(OP_OBS, Observation(100 + i % 50, NOW, rx_rssi=-90), 5)
    w.submit(OP_CONN_EVENT, ConnectionEventRecord(NOW, "IDLE", "SCANNING", "startup"))
    w.submit(OP_RADIO_EVENT, RadioEvent(NOW, EventLevel.INFO, "k", "m"), 5)
    assert w.flush(10)
    s = w.stats()
    assert s.written == 1003 and s.lost_ops == 0 and s.dropped_observations == 0
    w.stop()
    assert not w.is_alive() and w.stats().status == "stopped"
    assert not (tmp_path / "w.sqlite3-wal").exists() or (tmp_path / "w.sqlite3-wal").stat().st_size == 0
    w2 = DbWriter(p, now=lambda: NOW)
    w2.start()
    w2.wait_ready(5)
    assert len(w2.initial_nodes) == 50 and all(n.stale for n in w2.initial_nodes)
    w2.stop()


def test_writer_drops_only_observations_on_overflow(tmp_path):
    w = DbWriter(tmp_path / "o.sqlite3", max_queue=5)
    # not started: queue fills up
    for i in range(10):
        w.submit(OP_OBS, Observation(1, NOW), None)
    assert w.stats().dropped_observations == 5
    w.start()
    w.wait_ready(5)
    w.stop()


def test_writer_bad_op_does_not_lose_batch(tmp_path):
    w = DbWriter(tmp_path / "b.sqlite3")
    w.start()
    w.wait_ready(5)
    w.submit(OP_NODE, NodeRecord(1, NOW, NOW, latitude=123.0))  # violates CHECK constraint
    w.submit(OP_NODE, NodeRecord(2, NOW, NOW, long_name="ok"))
    w.flush(5)
    s = w.stats()
    assert s.lost_ops == 1 and "CHECK" in (s.last_error or "")
    w.stop()
    c = sqlite3.connect(tmp_path / "b.sqlite3")
    assert c.execute("SELECT node_num FROM nodes").fetchall() == [(2,)]


def test_writer_open_failure_reports_error(tmp_path):
    p = tmp_path / "n.sqlite3"
    r = open_database(p, NOW)
    r.conn.execute("PRAGMA user_version = 42")
    r.conn.close()
    w = DbWriter(p)
    w.start()
    assert w.wait_ready(5)
    assert w.stats().status == "error" and "newer" in (w.open_error or "")
    assert w.submit(OP_NODE, NodeRecord(1, NOW, NOW)) is False
    w.stop()
