# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""StatusService: aggregates DB writer stats and radio counters for the status bar (1 s poll)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from PySide6.QtCore import QObject, QTimer, Signal, Slot


@dataclass(frozen=True)
class StatusInfo:
    nodes_total: int = 0
    nodes_session: int = 0
    db_status: str = "starting"   # starting | ok | backlog | error | stopped
    db_path: str = ""
    db_detail: Optional[str] = None
    bad_packets: int = 0


class StatusService(QObject):
    changed = Signal(object)  # StatusInfo

    def __init__(self, writer: Any = None, interval_ms: int = 1000, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._writer = writer
        self._info = StatusInfo()
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.poll)

    @property
    def info(self) -> StatusInfo:
        return self._info

    def start(self) -> None:
        self.poll()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _update(self, **kw: Any) -> None:
        new = StatusInfo(**{**self._info.__dict__, **kw})
        if new != self._info:
            self._info = new
            self.changed.emit(new)

    @Slot()
    def poll(self) -> None:
        w = self._writer
        if w is None:
            self._update(db_status="error", db_detail="database not available")
            return
        s = w.stats()
        detail = []
        if s.last_error:
            detail.append(f"last error: {s.last_error}")
        if s.dropped_observations:
            detail.append(f"{s.dropped_observations} observations dropped (backlog)")
        if s.lost_ops:
            detail.append(f"{s.lost_ops} writes failed")
        if s.queue_len:
            detail.append(f"{s.queue_len} queued")
        self._update(db_status=s.status, db_path=s.path, db_detail="; ".join(detail) or None)

    @Slot(int, int)
    def on_counts(self, total: int, session: int) -> None:
        self._update(nodes_total=total, nodes_session=session)

    @Slot(object)
    def on_counters(self, counters: dict) -> None:
        bad = int(counters.get("bad_packets", 0))
        self._update(bad_packets=bad)
