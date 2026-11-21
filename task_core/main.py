# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Process entry for task-core. Refuses to run as uid 0."""

import argparse
import logging
import os
import signal
import sys
import threading
from pathlib import Path

from task_core import __version__
from task_core.api import Server
from task_core.auth import load_auth
from task_core.bus import Bus
from task_core.capabilities import Registry
from task_core.config import Config, load_config
from task_core.devices import LOGICAL, Manager, load_rules
from task_core.enumerator import NullEnumerator, UdevEnumerator
from task_core.exclusion import ExclusionError, guard
from task_core.errors import ApiError, ConfigError, EnumeratorError, PersistError, RootRefused
from task_core.modules import load_manifests, recompute_states
from task_core.persist import Store
from task_core.protocol_v2 import V2Handler
from task_core.sessions import DEFAULT_SESSIONS_FILE, SessionManager
from task_core.stream import StreamHub

logger = logging.getLogger("task_core")

# v2 core.health "hotplug" fields (H1)
HOTPLUG_FIELDS = ("state", "restarts", "missed", "events", "dispatch_errors", "last_error")

_DEVICE_TOPICS = {
    "device.appeared",
    "device.disappeared",
    "device.assigned",
    "device.unassigned",
}


class Core:
    def __init__(
        self,
        config: Config,
        enumerator_factory=None,
        euid_fn=None,
        idle_timeout: float = None,
        peer_uid_fn=None,
        extra_methods=None,
        clock=None,
        heartbeat_interval=None,
        stream_write_timeout=None,
        stream_check_interval=None,
    ) -> None:
        self.config = config
        self.euid_fn = euid_fn or os.geteuid
        self.enumerator_factory = enumerator_factory or UdevEnumerator
        self.peer_uid_fn = peer_uid_fn
        self.extra_methods = extra_methods
        self.idle_timeout = idle_timeout
        self.bus = Bus()
        self.auth = None
        self.devices = None
        self.capabilities = Registry(self.bus)
        self.manifests = []
        self.server = None
        self.clock = clock
        self.sessions = None
        self.streams = None
        self.v2 = None
        self._stream_options = {
            "heartbeat_interval": heartbeat_interval,
            "write_timeout": stream_write_timeout,
            "check_interval": stream_check_interval,
        }
        self._enumerator = None
        self._started_at = None
        self._wired = False
        self._stopped = False

    def open(self) -> None:
        if self.euid_fn() == 0:
            logger.error("refusing to run as uid 0")
            raise RootRefused()
        # A 1 ms GIL switch interval keeps RPC replies prompt while a burst of bus
        # events is being fanned out to streams (PHASE-2.md test 27, K8). Process-wide;
        # task-core is the only user of its interpreter. No protocol-visible change.
        sys.setswitchinterval(0.001)
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        self._check_state_owner()
        self.auth = load_auth(self.config.auth_file)
        sessions_file = getattr(self.config, "sessions_file", None) or DEFAULT_SESSIONS_FILE
        self.sessions = SessionManager(self.config.state_dir / "accounts.json", Path(sessions_file), self.clock)
        self.streams = StreamHub(self.bus, self.sessions, **self._stream_options)
        self.v2 = V2Handler(self)
        rules_path = self._rules_path()
        rules = load_rules(rules_path)
        store = Store(self.config.state_dir / "devices.json")
        self.devices = Manager(store, rules, self.bus)
        self.manifests = load_manifests(self.config.share_dir / "modules", self.bus)
        self._enumerator = self._open_enumerator()
        try:
            initial = self._enumerator.start(
                self.devices.appear, self.devices.disappear, self.devices.change
            )
        except EnumeratorError:
            logger.warning("udev unavailable; continuing with no devices")
            self._enumerator = NullEnumerator()
            initial = []
        self.devices.apply_enumerated(initial)
        begin = getattr(self._enumerator, "begin", None)
        if begin is not None:
            begin()  # live hot-plug events only after the startup list is registered (H1)
        self._refresh(announce=True)
        self.capabilities.mark_live()
        self.bus.subscribe(self._on_event)
        self._wired = True
        kwargs = {}
        if self.idle_timeout is not None:
            kwargs["idle_timeout"] = self.idle_timeout
        if self.peer_uid_fn is not None:
            kwargs["peer_uid_fn"] = self.peer_uid_fn
        if self.extra_methods is not None:
            kwargs["extra_methods"] = self.extra_methods
        self.server = Server(self, **kwargs)
        import time

        self._started_at = time.monotonic()
        self.server.start(self.config.socket)
        self.bus.publish("core.started", "core", {})

    def close(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        if self.server is not None:
            self.bus.publish("core.stopping", "core", {})
            if self.streams is not None:
                self.streams.shutdown()
            self.server.stop()
        if self._enumerator is not None:
            stop = getattr(self._enumerator, "stop", None)
            if stop is not None:
                stop()

    def handle_v2(self, payload: dict, uid: int):
        """Protocol v2 entry (section 5). Returns (response, subscriber-or-None)."""
        return self.v2.handle(payload, uid)

    def _check_state_owner(self) -> None:
        # K3 guard: logged only; behaviour is otherwise unchanged (section 4.1, item 11).
        try:
            owner = os.stat(self.config.state_dir).st_uid
        except OSError:
            return
        if owner != self.euid_fn():
            logger.warning("state dir not owned by service account")

    def wait(self) -> None:
        stopped = threading.Event()

        def _stop(_signum, _frame):
            stopped.set()

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
        stopped.wait()

    def call(self, method: str, params: dict) -> dict:
        if method == "core.health":
            return self._health()
        if method == "module.list":
            modules = [item.public() for item in self.manifests]
            modules.sort(key=lambda item: item["id"])
            return {"modules": modules}
        if method == "device.list":
            return self.devices.list_public()
        if method == "device.get":
            return self.devices.get_public(params)
        if method == "device.assign":
            return self._assign(params)
        if method == "device.unassign":
            logical = params.get("logical")
            if not isinstance(logical, str):
                raise ApiError("invalid-logical-device", "invalid logical device")
            try:
                return self.devices.unassign(logical)
            except PersistError:
                raise ApiError("internal-error", "internal error") from None
        if method == "capability.list":
            return self.capabilities.public()
        if method == "events.recent":
            return {"events": self.bus.recent()}
        raise ApiError("not-found", "unknown method")

    def _health(self) -> dict:
        import time

        started = self._started_at if self._started_at is not None else time.monotonic()
        return {
            "ok": True,
            "version": __version__,
            "uid": int(self.euid_fn()),
            "uptime_seconds": int(time.monotonic() - started),
        }

    def _assign(self, params: dict) -> dict:
        logical = params.get("logical")
        device_id = params.get("device_id")
        if not isinstance(logical, str) or logical not in LOGICAL:
            raise ApiError("invalid-logical-device", "invalid logical device")
        if not isinstance(device_id, str):
            raise ApiError("unknown-device", "unknown device")
        alias = params.get("alias", None)
        if alias is not None and not isinstance(alias, str):
            raise ApiError("bad-request", "invalid alias")
        try:
            return self.devices.assign(logical, device_id, alias)
        except PersistError:
            raise ApiError("internal-error", "internal error") from None

    def hotplug_status(self) -> dict:
        """Hot-plug monitor state for v2 core.health (H1). Never identifying."""
        status = getattr(self._enumerator, "status", None)
        if status is None:
            return {"state": "unknown"}
        try:
            current = status()
        except Exception:
            return {"state": "unknown"}
        return {key: current[key] for key in HOTPLUG_FIELDS if key in current}

    def _on_event(self, event: dict) -> None:
        if not self._wired:
            return
        topic = event.get("topic")
        if topic in _DEVICE_TOPICS:
            self._refresh(announce=True)
        elif topic == "capability.changed":
            recompute_states(self.manifests, self.capabilities.status, self.bus, True)

    def _refresh(self, announce: bool) -> None:
        logicals = self.devices.connected_logicals() if self.devices else set()
        self.capabilities.recompute(logicals)
        recompute_states(self.manifests, self.capabilities.status, self.bus, announce)

    def _open_enumerator(self):
        try:
            return self.enumerator_factory()
        except EnumeratorError:
            logger.warning("udev unavailable; continuing with no devices")
            return NullEnumerator()

    def _rules_path(self) -> Path:
        override = Path("/etc/task/devices/rules.yaml")
        if override.is_file():
            return override
        return self.config.share_dir / "devices" / "rules.yaml"


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="task-core")
    parser.add_argument("--config", default="/etc/task/core.toml")
    args = parser.parse_args(argv)
    try:
        config = load_config(Path(args.config))
    except ConfigError as exc:
        logger.error("%s", exc)
        return 2
    if os.geteuid() == 0:
        logger.error("refusing to run as uid 0")
        return 1
    try:
        lock = guard(config.state_dir, config.socket)
    except ExclusionError as exc:
        logger.error("%s", exc)
        return 3
    core = Core(config)
    try:
        core.open()
    except RootRefused:
        lock.release()
        return 1
    except Exception:
        logger.error("internal error source=startup")
        lock.release()
        return 1
    try:
        core.wait()
    finally:
        core.close()
        lock.release()
    return 0
