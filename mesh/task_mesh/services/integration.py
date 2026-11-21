# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4C integration: launcher status card, optional Maps geofeed, legacy data copy.

* Status card (task_comms.status): state, device label, node count, unread count. No content.
* Geofeed (task_comms.feeds, producer "task-mesh"): node positions only while the user has
  enabled "Show mesh nodes on Maps" (off by default, not persisted). Disabling clears the feed.
* Legacy copy: on first start, ~/.config|.local/state|.local/share|.cache/rain-mesh are COPIED
  (never moved) to the task-mesh directories if those do not exist yet. Old dirs stay.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)
STATE_MAP = {"CONNECTED": "connected", "CONNECTING": "connecting", "DEVICE_REBOOTING": "connecting",
             "BACKOFF": "connecting", "SCANNING": "connecting", "PORT_BUSY": "busy", "ERROR": "error",
             "PERMISSION_DENIED": "error"}


def copy_legacy_dirs(new_dirs, old_name: str = "rain-mesh") -> list[str]:
    copied = []
    for new in new_dirs:
        new = Path(new)
        old = new.parent / old_name
        if old.is_dir() and not new.exists():
            shutil.copytree(old, new, symlinks=True)
            new.chmod(0o700)
            if new.name == "task-mesh":
                for f in list(new.rglob("rain-mesh.*")):  # db/log file names of 0.1.0
                    target = f.with_name(f.name.replace("rain-mesh", "task-mesh", 1))
                    if not target.exists():
                        f.rename(target)
            copied.append(str(old))
            log.info("copied legacy data directory", extra={"event": "mesh.legacy_copy", "from_dir": str(old)})
    return copied


class StatusCard:
    def __init__(self, writer=None, clock=time.time):
        if writer is None:
            try:
                from task_comms.status import StatusWriter
                writer = StatusWriter("task-mesh", clock=clock)
            except Exception:  # noqa: BLE001 - launcher card is optional
                writer = None
        self.writer = writer
        self.state, self.device, self.nodes, self.unread, self.error = "disconnected", None, 0, 0, None

    def on_state(self, snap) -> None:
        self.state = STATE_MAP.get(getattr(snap, "state", ""), "disconnected")
        ident = getattr(snap, "identity", None)
        self.device = (getattr(ident, "short_name", None) or getattr(ident, "node_id", None)) if ident else None
        self.error = getattr(snap, "error_code", None) if self.state == "error" else None
        self.flush()

    def flush(self) -> None:
        if self.writer is None:
            return
        try:
            summary = f"{self.nodes} node{'s' if self.nodes != 1 else ''}"
            if self.unread:
                summary += f", {self.unread} unread"
            self.writer.write(self.state, device=self.device, summary=summary,
                              counts={"nodes": self.nodes, "unread": self.unread}, last_error=self.error)
        except OSError:
            pass

    def remove(self) -> None:
        if self.writer is not None:
            self.writer.remove()


class MapFeed:
    """Writes node positions to task-geofeed/1 only while enabled. Off by default."""

    def __init__(self, writer_factory=None):
        self._factory = writer_factory
        self.writer = None

    @property
    def enabled(self) -> bool:
        return self.writer is not None

    def set_enabled(self, on: bool, records=()) -> None:
        if on and self.writer is None:
            if self._factory is None:
                from task_comms.feeds import FeedWriter
                self.writer = FeedWriter("task-mesh")
            else:
                self.writer = self._factory()
            for r in records:
                self.update(r)
        elif not on and self.writer is not None:
            self.writer.clear()
            self.writer.close()
            self.writer = None

    def update(self, rec) -> None:
        if self.writer is None or rec.latitude is None or rec.longitude is None:
            return
        from task_comms.feeds import Entity
        ts = rec.position_time_radio or rec.last_rx_local or rec.updated_local
        try:
            self.writer.upsert(Entity(id=f"mesh:{rec.node_id or rec.node_num}", layer="mesh",
                                      label=rec.short_name or rec.long_name or rec.node_id or str(rec.node_num),
                                      lat=rec.latitude, lon=rec.longitude, alt_m=rec.altitude_m,
                                      observed_ts=int(ts), source="mesh-mqtt" if rec.via_mqtt else "mesh",
                                      stale_after_s=3 * 3600,
                                      attrs={"hw_model": rec.hw_model} if rec.hw_model else {}))
        except ValueError:
            pass
