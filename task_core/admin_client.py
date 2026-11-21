# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-core-admin session subcommands: terminal recovery and diagnostics (PHASE-2.md 10.2, D14).

These are ordinary protocol v2 clients. They authenticate a human with a password
through session.login, exactly like the console, and print only what task-core
returns. Standard library only: no Qt, no display, no hardware or state files.
"""

import errno
import json
import os
import signal
import socket
import time

from task_core.socketpath import TASK_SOCKET as DEFAULT_SOCKET, resolve_socket  # noqa: E402
LOGICALS = ("gps.primary", "mesh.primary", "sdr.primary", "radio.primary")
LOGICAL_CAPABILITY = {
    "gps.primary": "gps.position",
    "mesh.primary": "mesh.messaging",
    "sdr.primary": "radio.rx",
    "radio.primary": "radio.tx",
}
FACTORY_SERIALS = {"0001", "00000001"}
MAX_STDIN_PASSWORD = 4096
LOG_HINT = "task-core log: journalctl -u task-core -b"
UNSTABLE_NOTE = (
    "This device has no usable serial number. Its id depends on the USB port: moved to another port, "
    "it appears as a new device and any assignment shows Disconnected."
)
SHARED_NOTE = (
    "Identical units of this model may share this id. Use one per T.A.S.K. unit, "
    "or set a unique serial where the hardware allows."
)
SESSION_COMMANDS = ("status", "devices", "assignments", "events", "report", "assign", "unassign")
REFUSED_CODES = {"unauthenticated", "rate-limited", "forbidden", "would-displace"}
RECONNECT_AFTER = 20.0

# Test hook only (PHASE-2.md test 81): disabling it proves task-core itself refuses.
CLIENT_ROLE_CHECK = True

EXIT_OK, EXIT_USAGE, EXIT_ROOT, EXIT_REFUSED, EXIT_UNREACHABLE, EXIT_CANCELLED = 0, 1, 2, 3, 4, 5


class CliExit(Exception):
    def __init__(self, code, message=None):
        super().__init__(message or "")
        self.code = code
        self.message = message


class Interrupted(BaseException):
    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


class CoreUnavailable(Exception):
    pass


class TaskCoreError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def unreachable_message(path, exc) -> str:
    code = getattr(exc, "errno", None)
    if code in (errno.EACCES, errno.EPERM):
        return (f"No access to {path} \u2014 your account must be in group rain-core "
                "(log out and in after adding it).")
    reason = os.strerror(code) if code else str(exc) or "connection failed"
    return (f"task-core is not reachable at {path} ({reason}). "
            "Check: systemctl status task-core; journalctl -u task-core -b")


class Connection:
    """One RPC connection with transparent reconnect (the server closes idle RPC clients at 30 s)."""

    def __init__(self, path, connect_fn=None, clock=time.monotonic):
        self.path = path
        self.connect_fn = connect_fn or self._connect
        self.clock = clock
        self.sock = None
        self.buf = b""
        self.counter = 0
        self.last_used = 0.0

    @staticmethod
    def _connect(path):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(15)
        try:
            sock.connect(path)
        except OSError:
            sock.close()
            raise
        return sock

    def open(self):
        self.close()
        try:
            self.sock = self.connect_fn(self.path)
        except OSError as exc:
            raise CoreUnavailable(unreachable_message(self.path, exc)) from None
        self.buf = b""
        self.last_used = self.clock()

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def raw(self, body: dict) -> dict:
        if self.sock is None or self.clock() - self.last_used > RECONNECT_AFTER:
            self.open()
        for attempt in (1, 2):
            try:
                self.sock.sendall(json.dumps(body, separators=(",", ":")).encode("utf-8") + b"\n")
                reply = self._read()
                while reply.get("id") not in (body.get("id"), None):
                    reply = self._read()  # a late reply to an interrupted request
                self.last_used = self.clock()
                return reply
            except (OSError, EOFError):
                if attempt == 2:
                    raise CoreUnavailable(unreachable_message(self.path, OSError(errno.ECONNRESET, "")))
                self.open()
        raise CoreUnavailable("unreachable")

    def _read(self) -> dict:
        while b"\n" not in self.buf:
            chunk = self.sock.recv(262144)
            if not chunk:
                raise EOFError
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line.decode("utf-8"))

    def call(self, method, params=None, session=None) -> dict:
        self.counter += 1
        body = {"v": 2, "id": f"a{self.counter}", "method": method, "params": params or {}}
        if session is not None:
            body["session"] = session
        reply = self.raw(body)
        if reply.get("ok") is True:
            return reply["result"]
        error = reply.get("error") or {}
        raise TaskCoreError(error.get("code", "internal-error"), error.get("message", "internal error"))


def probe_protocol(conn: Connection) -> dict:
    """core.protocol first; a 0.1.x core answers v1 'unsupported version'."""
    reply = conn.raw({"v": 2, "id": "probe", "method": "core.protocol", "params": {}})
    if reply.get("v") == 2 and reply.get("ok") is True:
        return reply["result"]
    version = "0.1.x"
    try:
        health = conn.raw({"v": 1, "id": "ver", "method": "core.health", "params": {}})
        version = health.get("result", {}).get("version") or version
    except (CoreUnavailable, ValueError):
        pass
    raise CliExit(EXIT_UNREACHABLE, f"task-core {version} has no v2 sessions; 0.2.0 or later is required")


# ---------------------------------------------------------------- formatting

def dash(value) -> str:
    if value is None or value == "" or value == []:
        return "\u2014"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def device_name(device) -> str:
    return device.get("product") or device.get("manufacturer") or "\u2014"


def shared_identity(device) -> bool:
    serial = (device.get("serial") or "").strip()
    if serial == "" or set(serial) == {"0"} or serial in FACTORY_SERIALS:
        return True
    by_id = device.get("by_id") or ""
    if by_id and device.get("serial") is None:
        return True
    return False


def slot_line(logical, device) -> str:
    if device is None:
        return f"{logical} \u2192 Unassigned"
    alias = f'"{device["alias"]}"' if device.get("alias") is not None else "(no alias)"
    state = "Connected" if device.get("connected") else "Disconnected (assignment kept)"
    return f"{logical} \u2192 {device['id']} {alias} {state} \u00b7 {device_name(device)}"


def slots(listing) -> dict:
    by_id = {device["id"]: device for device in listing["devices"]}
    view = {}
    for logical in LOGICALS:
        entry = listing["assignments"].get(logical)
        if entry is None:
            view[logical] = None
        else:
            device = dict(by_id.get(entry["device_id"], {"id": entry["device_id"]}))
            device.setdefault("alias", entry.get("alias"))
            device["connected"] = entry.get("connected", device.get("connected"))
            view[logical] = device
    return view


def assign_effects(listing, logical, device_id):
    """Return (lines, displaced, warnings) exactly as the console's confirmation (8.5)."""
    by_id = {device["id"]: device for device in listing["devices"]}
    device = by_id.get(device_id)
    if device is None:
        return None, [], []
    lines = [f"{logical} \u2192 {device_name(device)} ({device_id})"]
    displaced = []
    for other in listing["devices"]:
        if other["id"] != device_id and other.get("logical") == logical:
            lines.append(f"{logical} will be removed from {device_name(other)} ({other['id']})")
            displaced.append({"logical": logical, "device_id": other["id"]})
    if device.get("logical") and device["logical"] != logical:
        lines.append(f"This device will lose {device['logical']}")
        displaced.append({"logical": device["logical"], "device_id": device_id})
    warnings = []
    capability = LOGICAL_CAPABILITY[logical]
    if capability not in (device.get("potential") or []):
        warnings.append(f"task-core will accept this, but this device is not classified for {capability}.")
    if not device.get("identity_stable", True):
        warnings.append(UNSTABLE_NOTE)
    if not device.get("connected"):
        lines.append("This device is not connected now; the assignment applies when it reconnects.")
    return lines, displaced, warnings


# ---------------------------------------------------------------- runner

class SessionRunner:
    def __init__(self, args, ctx):
        self.args = args
        self.ctx = ctx
        self.out = ctx.stdout
        self.err = ctx.stderr
        self.conn = Connection(resolve_socket(args.socket), ctx.connect)
        self.token = None
        self.login_result = None
        self.protocol = None
        self._logged_out = False

    def say(self, text=""):
        self.out.write(text + "\n")
        self.out.flush()

    def info(self, text=""):
        """Human-readable progress: stdout normally, stderr with --json (stdout stays pure JSON)."""
        stream = self.err if self.args.json else self.out
        stream.write(text + "\n")
        stream.flush()

    def warn(self, text):
        self.err.write(text + "\n")
        self.err.flush()

    def call(self, method, params=None):
        return self.conn.call(method, params, session=self.token)

    def run(self) -> int:
        args = self.args
        try:
            self.conn.open()
            self.protocol = probe_protocol(self.conn)
        except CoreUnavailable as exc:
            self.warn(str(exc))
            return EXIT_UNREACHABLE
        except CliExit as exc:
            self.warn(exc.message)
            return exc.code
        previous = self._install_signals()
        try:
            password = self._read_password()
            try:
                self.login_result = self.conn.call(
                    "session.login", {"username": args.user, "secret": password})
            finally:
                password = None
            self.token = self.login_result["session"]
            return self._dispatch()
        except TaskCoreError as exc:
            self.warn(f"task-core refused: {exc.message}")
            return EXIT_REFUSED if exc.code in REFUSED_CODES else EXIT_USAGE
        except CoreUnavailable as exc:
            self.warn(str(exc))
            return EXIT_UNREACHABLE
        except CliExit as exc:
            if exc.message:
                self.warn(exc.message)
            return exc.code
        except Interrupted as exc:
            self.warn(f"cancelled ({signal.Signals(exc.signum).name})")
            return EXIT_CANCELLED
        except KeyboardInterrupt:
            self.warn("cancelled (SIGINT)")
            return EXIT_CANCELLED
        except Exception as exc:  # never a traceback with request data; logout still runs
            self.warn(f"task-core-admin internal error ({type(exc).__name__})")
            return EXIT_USAGE
        finally:
            self._logout()
            self._restore_signals(previous)
            self.conn.close()

    # -- signals and logout ---------------------------------------------
    def _install_signals(self):
        previous = {}

        def handler(signum, _frame):
            raise Interrupted(signum)

        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            try:
                previous[signum] = signal.signal(signum, handler)
            except (ValueError, OSError):
                pass
        return previous

    def _restore_signals(self, previous):
        for signum, old in previous.items():
            try:
                signal.signal(signum, old)
            except (ValueError, OSError):
                pass

    def _logout(self):
        if self.token is None or self._logged_out:
            return
        self._logged_out = True
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            try:
                signal.signal(signum, signal.SIG_IGN)
            except (ValueError, OSError):
                pass
        token, self.token = self.token, None
        # A fresh connection: the current one may still carry an interrupted request.
        conn = Connection(self.conn.path, self.ctx.connect)
        try:
            conn.call("session.logout", {}, session=token)
        except (TaskCoreError, CoreUnavailable, OSError, ValueError):
            self.warn("logout could not be confirmed; the session expires at the idle limit")
        finally:
            token = None
            conn.close()

    # -- input ------------------------------------------------------------
    def _read_password(self) -> str:
        if self.args.password_stdin:
            data = self.ctx.stdin_bytes(MAX_STDIN_PASSWORD + 1)
            if len(data) > MAX_STDIN_PASSWORD:
                raise CliExit(EXIT_USAGE, "password input over 4096 bytes refused")
            if data.endswith(b"\r\n"):
                data = data[:-2]
            elif data.endswith(b"\n"):
                data = data[:-1]
            try:
                return data.decode("utf-8")
            except UnicodeDecodeError:
                raise CliExit(EXIT_USAGE, "password input is not valid UTF-8") from None
        return self.ctx.getpass(f"Password for {self.args.user}: ")

    def _confirm(self, word: str) -> None:
        tty = self.ctx.open_tty()
        if tty is None:
            raise CliExit(EXIT_USAGE, "no terminal for the confirmation; refusing (use --yes to confirm)")
        try:
            tty.write(f"Type {word} to continue: ")
            tty.flush()
            answer = tty.readline()
        finally:
            tty.close()
        if answer.rstrip("\r\n") != word:
            raise CliExit(EXIT_CANCELLED, "cancelled; nothing was sent")

    # -- commands -----------------------------------------------------------
    def _dispatch(self) -> int:
        command = self.args.command
        if command == "status":
            return self._emit(self._status())
        if command == "devices":
            return self._emit(self._devices())
        if command == "assignments":
            return self._emit(self._assignments())
        if command == "events":
            return self._emit(self._events())
        if command == "report":
            report = {}
            for part in (self._status(), self._devices(), self._assignments(), self._events()):
                report.update(part)
            return self._emit(report)
        if command == "assign":
            return self._assign()
        if command == "unassign":
            return self._unassign()
        raise CliExit(EXIT_USAGE, "unknown command")

    def _emit(self, results: dict) -> int:
        if self.args.json:
            self.say(json.dumps(results, indent=2, sort_keys=True, ensure_ascii=False))
        return EXIT_OK

    def _text(self, line=""):
        if not self.args.json:
            self.say(line)

    def _status(self) -> dict:
        health = self.call("core.health")
        protocol = self.call("core.protocol")
        whoami = self.call("session.whoami")
        counts = self.call("device.counts")
        capabilities = self.call("capability.list")
        modules = self.call("module.list")
        self._text("== task-core status ==")
        self._text(f"version: {dash(health.get('version'))}")
        self._text(f"service uid: {dash(health.get('uid'))}")
        self._text(f"uptime: {dash(health.get('uptime_seconds'))} s")
        self._text(f"protocol versions: {dash(protocol.get('versions'))}")
        self._text(f"boot_id: {dash(protocol.get('boot_id'))}")
        self._text(f"signed in: {dash(whoami.get('username'))} \u00b7 {dash(whoami.get('role'))}")
        self._text(f"devices: {counts['connected']} connected \u00b7 {counts['disconnected']} disconnected"
                   f" \u00b7 {counts['total']} total")
        self._text("capabilities:")
        for item in capabilities.get("capabilities", []):
            self._text(f"  {item['name']} ({item['kind']}): {item['status']}")
        self._text("modules:")
        for item in modules.get("modules", []):
            self._text(f"  {item['id']}: {item['state']} \u2014 {dash(item.get('reason'))}")
        self._text()
        return {"core.health": health, "core.protocol": protocol, "session.whoami": whoami,
                "device.counts": counts, "capability.list": capabilities, "module.list": modules}

    def _devices(self) -> dict:
        detail = getattr(self.args, "detail", None)
        if detail:
            params = {"logical": detail} if detail in LOGICALS else {"id": detail}
            result = self.call("device.get", params)
            self._text("== device detail ==")
            for key in ("id", "by_id", "vid", "pid", "serial", "manufacturer", "product", "subsystem", "class",
                        "potential", "identity_stable", "connected", "devnode", "logical", "alias"):
                self._text(f"{key}: {dash(result['device'].get(key))}")
            if not result["device"].get("identity_stable", True):
                self._text(f"note: {UNSTABLE_NOTE}")
            if shared_identity(result["device"]):
                self._text(f"note: {SHARED_NOTE}")
            self._text()
            return {"device.get": result}
        listing = self.call("device.list")
        self._text("== devices ==")
        for device in listing["devices"]:
            stable = "stable" if device.get("identity_stable") else "UNSTABLE (USB port)"
            state = "connected" if device.get("connected") else "disconnected"
            logical = device.get("logical") or "\u2014"
            alias = f'"{device["alias"]}"' if device.get("alias") is not None else "\u2014"
            self._text(f"{device['id']}  {dash(device.get('class'))}  {device_name(device)}  {state}  "
                       f"devnode={dash(device.get('devnode'))}  identity={stable}  logical={logical}  alias={alias}")
        self._text()
        return {"device.list": listing}

    def _assignments(self) -> dict:
        listing = self.call("device.list")
        self._text("== assignments ==")
        for logical, device in slots(listing).items():
            self._text(slot_line(logical, device))
        self._text()
        return {"assignments": listing}

    def _events(self) -> dict:
        since = getattr(self.args, "since", None)
        if since is not None:
            result = self.call("events.since", {"seq": since, "boot_id": self.protocol["boot_id"]})
            key = "events.since"
            if result.get("gap"):
                self._text("note: events were lost (gap); showing what the ring holds")
        else:
            result = self.call("events.recent")
            key = "events.recent"
        self._text("== events ==")
        for event in result["events"]:
            data = json.dumps(event.get("data"), sort_keys=True, ensure_ascii=False)
            self._text(f"seq={event['seq']} {event['time']} {event['topic']} {data}")
        self._text(LOG_HINT)
        self._text()
        return {key: result}

    def _require_admin(self, method):
        role = self.login_result["role"]
        if CLIENT_ROLE_CHECK and role != "administrator":
            raise CliExit(EXIT_REFUSED,
                          f"{method} requires administrator (signed in as {self.login_result['username']} \u00b7 {role})")

    def _assign(self) -> int:
        args = self.args
        self._require_admin("device.assign")
        listing = self.call("device.list")
        lines, displaced, warnings = assign_effects(listing, args.logical, args.device_id)
        if lines is None:
            raise CliExit(EXIT_USAGE, f"{args.device_id} is not a device known to task-core")
        self.info("This will:")
        for line in lines:
            self.info(f"  {line}")
        for warning in warnings:
            self.info(f"  WARNING: {warning}")
        if args.alias is not None:
            self.info(f'  alias: "{args.alias}"')
        confirm_displace = False
        if args.yes:
            if warnings and not args.accept_warnings:
                raise CliExit(EXIT_REFUSED, "warnings shown; add --accept-warnings to proceed (nothing was sent)")
            if displaced and args.replace:
                confirm_displace = True
        else:
            if warnings:
                self.info("The warnings above apply.")
            self._confirm("replace" if displaced else "yes")
            confirm_displace = bool(displaced)
        params = {"logical": args.logical, "device_id": args.device_id}
        if args.alias is not None:
            params["alias"] = args.alias
        if confirm_displace:
            params["confirm_displace"] = True
        result = self.call("device.assign", params)
        alias = f' alias "{result["alias"]}"' if result.get("alias") is not None else ""
        self.info(f"assigned: {result['logical']} \u2192 {result['device_id']}{alias}")
        for lost in result.get("displaced", []):
            self.info(f"  {lost['logical']} removed from {lost['device_id']}")
        if args.json:
            self.say(json.dumps({"device.assign": result}, indent=2, sort_keys=True))
        return EXIT_OK

    def _unassign(self) -> int:
        args = self.args
        self._require_admin("device.unassign")
        listing = self.call("device.list")
        device = slots(listing)[args.logical]
        if device is None:
            raise CliExit(EXIT_USAGE, f"{args.logical} is not assigned; nothing to do")
        alias = f'"{device["alias"]}"' if device.get("alias") is not None else "(no alias)"
        self.info("This will:")
        self.info(f"  unassign {args.logical} from {device_name(device)} ({device['id']}) alias {alias}")
        if not args.yes:
            self._confirm("yes")
        result = self.call("device.unassign", {"logical": args.logical})
        self.info(f"unassigned: {result['logical']}")
        if args.json:
            self.say(json.dumps({"device.unassign": result}, indent=2, sort_keys=True))
        return EXIT_OK


def run_session_command(args, ctx) -> int:
    if ctx.geteuid() == 0:
        ctx.stderr.write(f"run task-core-admin {args.command} as your normal user; root has no session bypass\n")
        return EXIT_ROOT
    if args.user is None:
        ctx.stderr.write(f"usage: task-core-admin {args.command} --user NAME [options]\n")
        return EXIT_USAGE
    return SessionRunner(args, ctx).run()


def run_probe(args, ctx) -> int:
    """probe / probe --public [--stream S]: no session is ever sent."""
    conn = Connection(resolve_socket(args.socket), ctx.connect)
    try:
        conn.open()
        protocol = probe_protocol(conn)
        if not args.public:
            ctx.stdout.write(json.dumps({"core.protocol": protocol}, sort_keys=True) + "\n")
            return EXIT_OK
        calls = [("core.protocol", {}), ("core.health", {}), ("module.list", {}), ("capability.list", {}),
                 ("device.counts", {}), ("session.whoami", {}),
                 ("events.since", {"seq": 0, "boot_id": protocol["boot_id"]})]
        for method, params in calls:
            reply = conn.raw({"v": 2, "id": method, "method": method, "params": params})
            ctx.stdout.write(json.dumps({"method": method, "params": params, "response": reply},
                                        sort_keys=True, ensure_ascii=False) + "\n")
        if args.stream:
            _probe_stream(args, ctx)
        ctx.stdout.flush()
        return EXIT_OK
    except CoreUnavailable as exc:
        ctx.stderr.write(str(exc) + "\n")
        return EXIT_UNREACHABLE
    except CliExit as exc:
        ctx.stderr.write(exc.message + "\n")
        return exc.code
    finally:
        conn.close()


def _probe_stream(args, ctx):
    conn = Connection(resolve_socket(args.socket), ctx.connect)
    conn.open()
    try:
        reply = conn.raw({"v": 2, "id": "stream", "method": "events.subscribe", "params": {"topics": []}})
        ctx.stdout.write(json.dumps({"method": "events.subscribe", "response": reply}, sort_keys=True) + "\n")
        if reply.get("ok") is not True:
            return
        deadline = time.monotonic() + float(args.stream)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            conn.sock.settimeout(remaining)
            try:
                frame = conn._read()
            except (socket.timeout, EOFError, OSError):
                break
            ctx.stdout.write(json.dumps({"frame": frame}, sort_keys=True, ensure_ascii=False) + "\n")
            ctx.stdout.flush()
    finally:
        conn.close()
