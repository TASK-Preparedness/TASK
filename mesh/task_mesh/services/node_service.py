# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""NodeService (GUI thread): merges radio data into NodeRecords, coalesces UI updates, persists.

Live updates are driven by received packets (meshtastic.receive.*): the library publishes
node.updated only during the config download (verified, design report §5.3). The radio's node DB is
snapshotted on CONNECTED and after a reboot re-handshake.
"""

from __future__ import annotations

import time
from typing import Callable, Iterable, Optional

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from task_mesh.database.writer import OP_NODE, OP_OBS
from task_mesh.domain.models import NodeInfoData, NodeRecord, Observation, StateSnapshot
from task_mesh.services.node_merge import merge_nodeinfo, merge_observation

COALESCE_MS = 250


class NodeService(QObject):
    rows_changed = Signal(object)        # list[NodeRecord] (changed or new rows)
    counts_changed = Signal(int, int)    # total known, heard this session

    def __init__(
        self,
        record: Optional[Callable[..., bool]] = None,
        now: Callable[[], int] = lambda: int(time.time()),
        coalesce_ms: int = COALESCE_MS,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._record = record
        self._now = now
        self._nodes: dict[int, NodeRecord] = {}
        self._session: set[int] = set()
        self._dirty: set[int] = set()
        self._radio_num: Optional[int] = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(coalesce_ms)
        self._timer.timeout.connect(self._flush)
        self.ui_flushes = 0

    # ----- read side ------------------------------------------------------------------------------
    @property
    def nodes(self) -> dict[int, NodeRecord]:
        return dict(self._nodes)

    @property
    def session_count(self) -> int:
        return len(self._session)

    def load_persisted(self, records: Iterable[NodeRecord]) -> None:
        for r in records:
            self._nodes[r.node_num] = r.with_changes(stale=True)
            self._dirty.add(r.node_num)
        self._flush()

    # ----- write side -----------------------------------------------------------------------------
    def _put(self, rec: NodeRecord) -> None:
        self._nodes[rec.node_num] = rec
        self._session.add(rec.node_num)
        self._dirty.add(rec.node_num)
        if self._record is not None:
            self._record(OP_NODE, rec)
        if not self._timer.isActive():
            self._timer.start()

    @Slot(object)
    def on_state(self, snap: StateSnapshot) -> None:
        if snap.identity is not None:
            self._radio_num = snap.identity.node_num

    @Slot(object)
    def on_snapshot(self, infos: list[NodeInfoData]) -> None:
        for info in infos:
            self.on_nodeinfo(info)

    @Slot(object)
    def on_nodeinfo(self, info: NodeInfoData) -> None:
        self._put(merge_nodeinfo(self._nodes.get(info.node_num), info, self._now(), self._radio_num))

    @Slot(object)
    def on_observation(self, obs: Observation) -> None:
        rec = merge_observation(self._nodes.get(obs.node_num), obs, self._radio_num)
        self._put(rec)
        if self._record is not None:
            self._record(OP_OBS, obs, self._radio_num)

    @Slot()
    def _flush(self) -> None:
        if not self._dirty:
            return
        rows = [self._nodes[n] for n in sorted(self._dirty) if n in self._nodes]
        self._dirty.clear()
        self.ui_flushes += 1
        self.rows_changed.emit(rows)
        self.counts_changed.emit(len(self._nodes), len(self._session))
