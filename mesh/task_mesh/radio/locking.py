# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""0.3.0: the GUI's Meshtastic provider takes the same per-device lock as task-mesh-service, so a radio is never
opened by both. Busy -> ConnectError(PORT_BUSY, "in use by service (pid N)")."""

from __future__ import annotations

from typing import Any

from task_mesh.core.errors import ErrorCode
from task_mesh.hub.locks import Busy, device_lock
from task_mesh.radio.base import ConnectError


class LockingProvider:
    def __init__(self, inner: Any, role: str = "gui", lock_factory=device_lock) -> None:
        self._inner = inner
        self._role = role
        self._lock_factory = lock_factory
        self._lock = None

    def connect(self, candidate, generation: int):
        self._release()
        lock = self._lock_factory(candidate.open_path or candidate.device, self._role)
        try:
            lock.acquire()
        except Busy as b:
            raise ConnectError(ErrorCode.PORT_BUSY, f"in use by {b.owner} (T.A.S.K. background service?)") from None
        self._lock = lock
        try:
            return self._inner.connect(candidate, generation)
        except BaseException:
            self._release()
            raise

    def _release(self) -> None:
        lock, self._lock = self._lock, None
        if lock is not None:
            lock.release()

    def close(self) -> None:
        try:
            self._inner.close()
        finally:
            self._release()

    def shutdown(self) -> None:
        try:
            getattr(self._inner, "shutdown", self._inner.close)()
        finally:
            self._release()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
