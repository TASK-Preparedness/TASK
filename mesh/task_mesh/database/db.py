# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Open the SQLite database: pragmas, integrity check, quarantine, migrations (design report §6.1)."""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_MIG_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")

PRAGMAS = (
    "PRAGMA synchronous = NORMAL",
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 5000",
    "PRAGMA temp_store = MEMORY",
    "PRAGMA wal_autocheckpoint = 1000",
    "PRAGMA journal_size_limit = 16777216",
)


class DatabaseError(Exception):
    pass


class SchemaTooNewError(DatabaseError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum: str


@dataclass
class OpenResult:
    conn: sqlite3.Connection
    path: Path
    quarantined: Optional[Path] = None
    applied: list[int] = field(default_factory=list)
    backups: list[Path] = field(default_factory=list)
    schema_version: int = 0


def load_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    migs = []
    for p in sorted(directory.glob("*.sql")):
        m = _MIG_RE.match(p.name)
        if not m:
            continue
        raw = p.read_bytes()
        migs.append(Migration(int(m.group(1)), m.group(2), raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()))
    versions = [m.version for m in migs]
    if versions != list(range(1, len(versions) + 1)):
        raise DatabaseError(f"migration files are not contiguous: {versions}")
    return migs


def _utc_stamp(now: int) -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))


def quarantine(path: Path, now: int) -> Path:
    """Rename a broken DB (and its -wal/-shm) aside. Never deletes user data."""
    target = path.with_name(f"{path.name}.corrupt-{_utc_stamp(now)}")
    n = 1
    while target.exists():
        target = path.with_name(f"{path.name}.corrupt-{_utc_stamp(now)}-{n}")
        n += 1
    path.rename(target)
    for suffix in ("-wal", "-shm"):
        side = path.with_name(path.name + suffix)
        if side.exists():
            side.rename(target.with_name(target.name + suffix))
    log.error("database quarantined to %s", target, extra={"event": "db.quarantine"})
    return target


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=True, timeout=5.0)
    return conn


def _integrity_ok(path: Path) -> bool:
    try:
        conn = _connect(path)
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
            return bool(row) and row[0] == "ok"
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return False


def apply_pragmas(conn: sqlite3.Connection) -> None:
    mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
    if str(mode).lower() != "wal":
        raise DatabaseError(f"could not enable WAL (journal_mode={mode})")
    for p in PRAGMAS:
        conn.execute(p)


def _has_tables(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0] > 0


def migrate(conn: sqlite3.Connection, path: Optional[Path], now: int,
            migrations: Optional[list[Migration]] = None) -> tuple[list[int], list[Path]]:
    migs = migrations if migrations is not None else load_migrations()
    known = migs[-1].version if migs else 0
    user_version = conn.execute("PRAGMA user_version").fetchone()[0]
    if user_version > known:
        raise SchemaTooNewError(
            f"database schema version {user_version} is newer than this app supports ({known}); "
            "it was written by a newer T.A.S.K. version. Install that version or move the file aside."
        )
    applied_rows: dict[int, str] = {}
    if _has_tables(conn):
        try:
            applied_rows = dict(conn.execute("SELECT version, checksum FROM schema_migrations").fetchall())
        except sqlite3.OperationalError:
            applied_rows = {}
    elif user_version == 0:
        # Brand-new database: auto_vacuum must be set before the first table exists.
        conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
    if applied_rows and max(applied_rows) > known:
        raise SchemaTooNewError(f"database has migration {max(applied_rows)} unknown to this app ({known})")
    for m in migs:
        if m.version in applied_rows and applied_rows[m.version] != m.checksum:
            raise DatabaseError(f"checksum mismatch for applied migration {m.version:04d}_{m.name}")
    pending = [m for m in migs if m.version not in applied_rows]
    backups: list[Path] = []
    if pending and applied_rows and path is not None:
        bak = path.with_name(f"{path.name}.pre-v{pending[0].version:04d}.bak")
        dst = sqlite3.connect(str(bak))
        try:
            conn.backup(dst)
        finally:
            dst.close()
        backups.append(bak)
        log.info("backup before migration: %s", bak, extra={"event": "db.backup"})
    done = []
    for m in pending:
        script = (
            "BEGIN IMMEDIATE;\n" + m.sql + "\n;"
            f"INSERT INTO schema_migrations(version, name, checksum, applied_at) "
            f"VALUES ({m.version}, '{m.name}', '{m.checksum}', {int(now)});\n"
            f"PRAGMA user_version = {m.version};\nCOMMIT;"
        )
        try:
            conn.executescript(script)
        except sqlite3.Error as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise DatabaseError(f"migration {m.version:04d}_{m.name} failed: {exc}") from exc
        done.append(m.version)
        log.info("applied migration %04d_%s", m.version, m.name, extra={"event": "db.migrate"})
    return done, backups


def open_database(path: Path, now: Optional[int] = None,
                  migrations: Optional[list[Migration]] = None) -> OpenResult:
    now = int(time.time()) if now is None else now
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    quarantined = None
    if path.exists() and not _integrity_ok(path):
        quarantined = quarantine(path, now)
    fresh = not path.exists() or path.stat().st_size == 0
    conn = _connect(path)
    try:
        if fresh:
            # Must precede journal_mode=WAL and the first CREATE TABLE (verified: WAL first leaves it 0).
            conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
        apply_pragmas(conn)
        applied, backups = migrate(conn, path, now, migrations)
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
    except BaseException:
        conn.close()
        raise
    log.info("database open (schema v%d)", ver, extra={"event": "db.open"})
    return OpenResult(conn, path, quarantined, applied, backups, ver)


def checkpoint_and_close(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error as exc:
        log.warning("checkpoint failed: %s", exc, extra={"event": "db.checkpoint"})
    finally:
        conn.close()


NowFn = Callable[[], int]
