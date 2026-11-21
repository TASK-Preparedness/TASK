# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""DbWriter: the single thread that owns the only read-write SQLite connection (design report §6.1).

* Bounded queue (10 000). On overflow only *observations* are dropped (counted); node upserts and events
  block briefly instead and are counted as lost only if the writer is wedged.
* One transaction per batch: 250 ms or 200 operations, whichever comes first.
* Retention prune at startup and hourly. Drain + wal_checkpoint(TRUNCATE) on stop.
* Never raises into callers; failures are visible through stats() (DB status in the status bar).
"""

from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from task_mesh.core.config import RetentionConfig
from task_mesh.database import repo
from task_mesh.database.db import OpenResult, checkpoint_and_close, open_database
from task_mesh.domain.models import NodeRecord

log = logging.getLogger(__name__)

OP_NODE = "node"
OP_OBS = "obs"
OP_CONN_EVENT = "conn_event"
OP_RADIO_EVENT = "radio_event"
OP_RADIO = "radio"
_STOP = object()


@dataclass
class _Barrier:
    event: threading.Event = field(default_factory=threading.Event)


@dataclass(frozen=True)
class WriterStats:
    status: str               # starting | ok | backlog | error | stopped
    path: str
    queue_len: int
    written: int
    dropped_observations: int
    lost_ops: int
    last_error: Optional[str]
    quarantined: Optional[str]
    schema_version: int


class DbWriter(threading.Thread):
    def __init__(
        self,
        path: Path,
        retention: RetentionConfig = RetentionConfig(),
        now: Callable[[], int] = lambda: int(time.time()),
        max_queue: int = 10000,
        batch_s: float = 0.25,
        batch_ops: int = 200,
        prune_interval_s: float = 3600.0,
    ) -> None:
        super().__init__(name="task-db", daemon=True)
        self.path = path
        self._ret = retention
        self._now = now
        self._q: "queue.Queue[Any]" = queue.Queue(maxsize=max_queue)
        self._batch_s = batch_s
        self._batch_ops = batch_ops
        self._prune_interval = prune_interval_s
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._status = "starting"
        self._written = 0
        self._dropped = 0
        self._lost = 0
        self._last_error: Optional[str] = None
        self._open: Optional[OpenResult] = None
        self.initial_nodes: list[NodeRecord] = []
        self.open_error: Optional[str] = None
        self.last_prune: Optional[dict] = None
        self._backlog_threshold = max(1, max_queue // 10)

    # ----- caller side (any thread) ------------------------------------------------------------
    def wait_ready(self, timeout: float = 10.0) -> bool:
        return self._ready.wait(timeout)

    def submit(self, op: str, *args: Any) -> bool:
        if self._status in ("error", "stopped"):
            if op == OP_OBS:
                self._dropped += 1
            else:
                self._lost += 1
            return False
        item = (op, args)
        try:
            if op == OP_OBS:
                self._q.put_nowait(item)
            else:
                self._q.put(item, timeout=1.0)
            return True
        except queue.Full:
            with self._lock:
                if op == OP_OBS:
                    self._dropped += 1
                else:
                    self._lost += 1
            return False

    def flush(self, timeout: float = 5.0) -> bool:
        """Block until everything submitted before this call is committed (tests, shutdown)."""
        if not self.is_alive():
            return False
        b = _Barrier()
        try:
            self._q.put(b, timeout=timeout)
        except queue.Full:
            return False
        return b.event.wait(timeout)

    def stop(self, timeout: float = 3.0) -> None:
        if self.is_alive():
            try:
                self._q.put(_STOP, timeout=timeout)
            except queue.Full:
                pass
            self.join(timeout + 2.0)

    def stats(self) -> WriterStats:
        qlen = self._q.qsize()
        status = self._status
        if status == "ok" and (qlen >= self._backlog_threshold or self._dropped or self._lost):
            status = "backlog"
        o = self._open
        return WriterStats(
            status=status, path=str(self.path), queue_len=qlen, written=self._written,
            dropped_observations=self._dropped, lost_ops=self._lost, last_error=self._last_error,
            quarantined=str(o.quarantined) if o and o.quarantined else None,
            schema_version=o.schema_version if o else 0,
        )

    @property
    def open_result(self) -> Optional[OpenResult]:
        return self._open

    # ----- writer thread -----------------------------------------------------------------------
    def run(self) -> None:
        try:
            self._open = open_database(self.path, self._now())
            conn = self._open.conn
            self.initial_nodes = repo.load_nodes(conn)
            self._prune(conn)
            self._status = "ok"
        except BaseException as exc:  # noqa: BLE001
            self.open_error = f"{type(exc).__name__}: {exc}"
            self._last_error = self.open_error
            self._status = "error"
            log.error("database unavailable: %s", self.open_error, extra={"event": "db.open_failed"})
            self._ready.set()
            self._drain_discard()
            return
        self._ready.set()
        next_prune = time.monotonic() + self._prune_interval
        try:
            self._loop(conn, next_prune)
        finally:
            checkpoint_and_close(conn)
            if self._status != "error":
                self._status = "stopped"
            log.info("database closed", extra={"event": "db.close"})

    def _drain_discard(self) -> None:
        while True:
            item = self._q.get()
            if item is _STOP:
                return
            if isinstance(item, _Barrier):
                item.event.set()

    def _loop(self, conn: sqlite3.Connection, next_prune: float) -> None:
        while True:
            try:
                first = self._q.get(timeout=1.0)
            except queue.Empty:
                first = None
            if time.monotonic() >= next_prune:
                self._prune(conn)
                next_prune = time.monotonic() + self._prune_interval
            if first is None:
                continue
            batch, barriers, stop = [], [], False
            deadline = time.monotonic() + self._batch_s
            item = first
            while True:
                if item is _STOP:
                    stop = True
                elif isinstance(item, _Barrier):
                    barriers.append(item)
                else:
                    batch.append(item)
                if stop or len(batch) >= self._batch_ops:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0 and not barriers:
                    break
                try:
                    item = self._q.get(timeout=max(0.0, remaining)) if remaining > 0 else self._q.get_nowait()
                except queue.Empty:
                    break
            if batch:
                self._commit(conn, batch)
            for b in barriers:
                b.event.set()
            if stop:
                # Drain anything that raced in behind the stop marker.
                rest = []
                while True:
                    try:
                        it = self._q.get_nowait()
                    except queue.Empty:
                        break
                    if isinstance(it, _Barrier):
                        it.event.set()
                    elif it is not _STOP:
                        rest.append(it)
                if rest:
                    self._commit(conn, rest)
                return

    def _apply(self, conn: sqlite3.Connection, op: str, args: tuple) -> None:
        if op == OP_NODE:
            repo.upsert_node(conn, *args)
        elif op == OP_OBS:
            repo.insert_observation(conn, *args)
        elif op == OP_CONN_EVENT:
            repo.insert_connection_event(conn, *args)
        elif op == OP_RADIO_EVENT:
            repo.insert_radio_event(conn, *args)
        elif op == OP_RADIO:
            repo.upsert_radio(conn, *args)
        else:
            raise ValueError(f"unknown op {op}")

    def _commit(self, conn: sqlite3.Connection, batch: list) -> None:
        try:
            conn.execute("BEGIN IMMEDIATE")
            for op, args in batch:
                try:
                    conn.execute("SAVEPOINT op")
                    self._apply(conn, op, args)
                    conn.execute("RELEASE op")
                except (sqlite3.IntegrityError, ValueError, TypeError) as exc:
                    # One bad row must not lose the batch.
                    conn.execute("ROLLBACK TO op")
                    conn.execute("RELEASE op")
                    self._lost += 1
                    self._last_error = f"{type(exc).__name__}: {exc}"
                    log.warning("db op %s rejected: %s", op, exc, extra={"event": "db.op_rejected"})
            conn.execute("COMMIT")
            self._written += len(batch)
        except sqlite3.Error as exc:
            if conn.in_transaction:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            self._lost += len(batch)
            self._last_error = f"{type(exc).__name__}: {exc}"
            log.error("db batch failed: %s", exc, extra={"event": "db.batch_failed"})

    def _prune(self, conn: sqlite3.Connection) -> None:
        try:
            self.last_prune = repo.prune(conn, self._ret, self._now())
            log.info("retention prune %s", self.last_prune, extra={"event": "db.prune"})
        except sqlite3.Error as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            self._last_error = f"prune: {exc}"
            log.warning("prune failed: %s", exc, extra={"event": "db.prune_failed"})
