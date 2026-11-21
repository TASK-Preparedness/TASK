# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-mesh-service: headless owner of the user's assigned mesh radios (task-mesh 0.3.0).

* Runs as the desktop user via systemd --user (task-mesh-service.service). Installed, NOT enabled; the user
  enables it explicitly (Mesh > Network Status, or `systemctl --user enable --now task-mesh-service`).
* Single instance ($XDG_RUNTIME_DIR/task/mesh-service.lock); one owner per radio (per-device locks shared with
  the GUI). Opens only devices explicitly assigned to a protocol. Never flashes or changes radio settings.
* Never transmits by itself: no beacon, relay, auto-reply or forwarding. Sending happens only when the GUI
  forwards an explicit user action with a verified operator session.
* Qt-free: notifications use the session bus via jeepney. Refuses to run as root.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Optional, Sequence

from task_mesh import __version__

log = logging.getLogger("task_mesh.service")
VENDOR_DIR = Path(__file__).resolve().parent / "_vendor"


def build_hub(paths, role: str, sender=None, factories=None, scan=None, lock_factory=None, comms_store=None,
              session_role=None):
    from task_comms.notifications import NotificationStore

    from task_mesh.hub.devices import Assignments
    from task_mesh.hub.engine import Hub
    from task_mesh.hub.store import HubStore
    from task_mesh.protocols.meshcore.adapter import MeshCoreAdapter
    from task_mesh.protocols.meshtastic_adapter import MeshtasticAdapter

    factories = factories or {"meshtastic": lambda path, key, sink: MeshtasticAdapter(path, key, sink),
                              "meshcore": lambda path, key, sink: MeshCoreAdapter(path, key, sink)}
    kw = {}
    if session_role is not None:
        kw["session_role"] = session_role
    return Hub(HubStore(paths.data_dir / "hub.sqlite3"), comms_store or NotificationStore(),
               Assignments(paths.config_dir / "radio-protocols.json"), factories, role,
               notify_config=paths.config_dir / "notifications.json", sender=sender, scan=scan,
               lock_factory=lock_factory, **kw)


GUI_BIN = "/usr/bin/task-mesh"


def launch_gui(row_id: int, env=None) -> bool:
    """Start the Mesh window at one message: argv only, the argument is an internal integer row id (never content).
    Needs DISPLAY in this service's environment (see SERVICE.md, opt-in import-environment)."""
    import subprocess
    env = dict(os.environ if env is None else env)
    if not env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY"):
        log.info("notification click: no DISPLAY in the service environment; window not started",
                 extra={"event": "service.open_no_display"})
        return False
    if not os.path.exists(GUI_BIN):
        return False
    subprocess.Popen([GUI_BIN, "--open-message", str(int(row_id))], env=env, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    return True


def run(stop: threading.Event, paths=None, poll_s: float = 3.0, hub_kwargs: Optional[dict] = None,
        env=None) -> int:
    from task_mesh.core.paths import resolve_paths
    from task_mesh.hub.ipc import IpcServer, socket_path
    from task_mesh.hub.locks import Busy, instance_lock
    from task_mesh.hub.notifier import JeepneySender

    lock = instance_lock(env)
    try:
        lock.acquire()
    except Busy as b:
        print(f"task-mesh-service is already running ({b.owner})", file=sys.stderr)
        return 3
    try:
        paths = paths or resolve_paths()
        paths.ensure()
        kw = dict(hub_kwargs or {})
        holder: dict = {}
        if "sender" not in kw:
            kw["sender"] = JeepneySender(on_action=lambda nid, act: holder["hub"].on_notification_action(nid, act),
                                         on_closed=lambda nid: holder["hub"].notifier.closed(nid))
        launch = kw.pop("launch_gui", launch_gui)
        hub = build_hub(paths, "service", **kw)
        holder["hub"] = hub
        ipc = IpcServer(hub.api, socket_path(env), on_close=hub.drop_client)
        hub.listeners.append(ipc.publish)
        # notification click: an attached window gets the "open" event; with no window, start one
        hub.opener = lambda ref: True if ipc.subscribers() else launch(ref["id"])
        ipc.start()
        log.info("task-mesh-service %s started", __version__, extra={"event": "service.start"})
        n = 0
        try:
            while not stop.is_set():
                hub.devices.poll()
                n += 1
                if n % 20 == 0:
                    hub.recheck_auth()
                stop.wait(poll_s)
        finally:
            ipc.stop()
            hub.shutdown()
            hub.store.close()
            log.info("task-mesh-service stopped", extra={"event": "service.stop"})
        return 0
    finally:
        lock.release()


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="task-mesh-service", description="T.A.S.K. Mesh background radio service")
    p.add_argument("--version", action="store_true")
    p.add_argument("--status", action="store_true", help="print the running service's status (read-only) and exit")
    p.add_argument("--debug", action="store_true")
    a = p.parse_args(list(sys.argv[1:] if argv is None else argv))
    if a.version:
        print(f"task-mesh-service {__version__}")
        return 0
    if os.geteuid() == 0:
        print("task-mesh-service must not run as root; it runs as the desktop user (systemd --user).", file=sys.stderr)
        return 2
    if a.status:
        import json

        from task_mesh.hub.ipc import HubClient, IpcError
        try:
            print(json.dumps(HubClient().call("status"), indent=2, default=str))
            return 0
        except IpcError as exc:
            print(f"not running: {exc}", file=sys.stderr)
            return 1
    if str(VENDOR_DIR) not in sys.path and VENDOR_DIR.is_dir():
        sys.path.insert(0, str(VENDOR_DIR))
    from task_mesh.core.logging_setup import clamp_library_loggers, setup_logging
    from task_mesh.core.paths import resolve_paths
    paths = resolve_paths()
    paths.ensure()
    setup_logging(paths.log_dir / "task-mesh-service.jsonl", "DEBUG" if a.debug else "INFO", console=True)
    clamp_library_loggers()
    from task_mesh.protocols.meshcore.compat import quiet_logger
    quiet_logger()
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    return run(stop, paths)


if __name__ == "__main__":
    sys.exit(main())
