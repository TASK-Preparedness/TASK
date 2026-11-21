# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-core-admin: account administration and terminal recovery (PHASE-2.md 6.1, 10.2).

Account commands (user ..., client ...) run as root. The accounts.json work is
done in a forked child that has dropped to the task-core service account
(setgroups([]), setgid, setuid). They never need a running task-core and never
touch devices.json or hardware.

Session subcommands (status, devices, assignments, events, report, assign,
unassign) and probe run as the invoking normal user and talk only to the
task-core socket (see admin_client.py).
"""

import argparse
import contextlib
import fcntl
import getpass
import grp
import io
import os
import pwd
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from task_core import admin_client
from task_core.accounts import ACCOUNT_ROLES, AccountsError, now_stamp, parse_document, render_document, valid_username
from task_core.passwords import PolicyError, check_for_set, hash_password
from task_core.persist import Store, fsync_directory

SERVICE_USER = "rain-core"
SERVICE_GROUP = "rain-core"
DEFAULT_CONFIG = "/etc/task/core.toml"
DEFAULT_STATE_DIR = "/var/lib/task"
DEFAULT_SESSIONS = "/etc/task/sessions.toml"
ROOT_REQUIRED = "this command must run as root (it edits {what} as the {who} account)"


class _Ops:
    """Privilege primitives. Tests replace these with spies (PHASE-2.md test 22)."""

    def __init__(self):
        self.setgroups = os.setgroups
        self.setgid = os.setgid
        self.setuid = os.setuid

    def fork_and_wait(self, child) -> int:
        sys.stdout.flush()
        sys.stderr.flush()
        pid = os.fork()
        if pid == 0:
            code = 1
            try:
                code = child()
            except BaseException:
                code = 1
            finally:
                try:
                    sys.stdout.flush()
                    sys.stderr.flush()
                finally:
                    os._exit(code)
        _pid, status = os.waitpid(pid, 0)
        return os.waitstatus_to_exitcode(status)


class _Tty:
    """The controlling terminal, opened the way getpass opens it (no stdin/stdout involved)."""

    def __init__(self, fd):
        self._raw = io.FileIO(fd, "r+")
        self._text = io.TextIOWrapper(self._raw, encoding="utf-8", errors="replace", line_buffering=True)

    def write(self, text):
        self._text.write(text)

    def flush(self):
        self._text.flush()

    def readline(self):
        return self._text.readline()

    def close(self):
        try:
            self._text.close()
        except OSError:
            pass


def _open_tty():
    try:
        fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    except OSError:
        return None
    return _Tty(fd)


def _stdin_bytes(limit: int) -> bytes:
    return sys.stdin.buffer.read(limit)


@dataclass
class Context:
    geteuid: object = os.geteuid
    getpass: object = getpass.getpass
    stdin_bytes: object = _stdin_bytes
    open_tty: object = _open_tty
    stdout: object = None
    stderr: object = None
    connect: object = None
    getpwnam: object = pwd.getpwnam
    getgrnam: object = grp.getgrnam
    ops: object = field(default_factory=_Ops)

    def __post_init__(self):
        self.stdout = self.stdout or sys.stdout
        self.stderr = self.stderr or sys.stderr


class _Parser(argparse.ArgumentParser):
    """Usage errors exit 1 (PHASE-2.md 10.2 item 10); exit 2 is reserved for 'run as root'."""

    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write(f"{self.prog}: error: {message}\n")
        raise SystemExit(admin_client.EXIT_USAGE)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="task-core-admin", allow_abbrev=False,
                     description="T.A.S.K. core accounts and terminal recovery")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="group", required=True, parser_class=_Parser)

    user = sub.add_parser("user", help="manage accounts (root)", allow_abbrev=False)
    user_sub = user.add_subparsers(dest="action", required=True, parser_class=_Parser)
    add = user_sub.add_parser("add", allow_abbrev=False)
    add.add_argument("name")
    add.add_argument("--role", required=True, choices=ACCOUNT_ROLES)
    for action in ("passwd", "disable", "enable", "remove"):
        item = user_sub.add_parser(action, allow_abbrev=False)
        item.add_argument("name")
    user_sub.add_parser("list", allow_abbrev=False)

    client = sub.add_parser("client", help="edit the sessions.toml login allow-list (root)", allow_abbrev=False)
    client_sub = client.add_subparsers(dest="action", required=True, parser_class=_Parser)
    for action in ("allow", "remove"):
        item = client_sub.add_parser(action, allow_abbrev=False)
        item.add_argument("username")

    probe = sub.add_parser("probe", help="v2 protocol probe; never sends a session", allow_abbrev=False)
    probe.add_argument("--public", action="store_true")
    probe.add_argument("--stream", type=float, default=0)
    probe.add_argument("--socket")

    def session_options(item):
        item.add_argument("--user")
        item.add_argument("--password-stdin", action="store_true")
        item.add_argument("--json", action="store_true")
        item.add_argument("--socket")

    for name in ("status", "assignments", "report"):
        session_options(sub.add_parser(name, allow_abbrev=False))
    devices = sub.add_parser("devices", allow_abbrev=False)
    session_options(devices)
    devices.add_argument("--detail", metavar="ID|LOGICAL")
    events = sub.add_parser("events", allow_abbrev=False)
    session_options(events)
    events.add_argument("--since", type=_seq, metavar="SEQ")
    assign = sub.add_parser("assign", allow_abbrev=False)
    assign.add_argument("logical", choices=admin_client.LOGICALS)
    assign.add_argument("device_id")
    assign.add_argument("--alias")
    assign.add_argument("--yes", action="store_true")
    assign.add_argument("--replace", action="store_true")
    assign.add_argument("--accept-warnings", action="store_true")
    session_options(assign)
    unassign = sub.add_parser("unassign", allow_abbrev=False)
    unassign.add_argument("logical", choices=admin_client.LOGICALS)
    unassign.add_argument("--yes", action="store_true")
    session_options(unassign)
    return parser


def _seq(text):
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("SEQ must be >= 0")
    return value


def main(argv=None, ctx=None) -> int:
    ctx = ctx or Context()
    parser = build_parser()
    try:
        with contextlib.redirect_stderr(ctx.stderr), contextlib.redirect_stdout(ctx.stdout):
            args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    if args.group in admin_client.SESSION_COMMANDS:
        args.command = args.group
        return admin_client.run_session_command(args, ctx)
    if args.group == "probe":
        return admin_client.run_probe(args, ctx)
    if args.group == "user":
        return _user(args, ctx)
    if args.group == "client":
        return _client(args, ctx)
    return admin_client.EXIT_USAGE


# ---------------------------------------------------------------- paths

def _paths(args):
    """state_dir and sessions file from core.toml when present; otherwise the fixed defaults."""
    state_dir, sessions = Path(DEFAULT_STATE_DIR), Path(DEFAULT_SESSIONS)
    config = Path(args.config)
    if config.is_file():
        from task_core.config import load_config

        loaded = load_config(config)
        state_dir = loaded.state_dir
        if loaded.sessions_file is not None:
            sessions = loaded.sessions_file
    return state_dir, sessions


# ---------------------------------------------------------------- user ...

def _err(ctx, text):
    ctx.stderr.write(text + "\n")
    ctx.stderr.flush()


def _out(ctx, text):
    ctx.stdout.write(text + "\n")
    ctx.stdout.flush()


def read_new_password(ctx, name) -> str:
    """Prompt twice with no echo; apply the D4 policy. getpass removes only the line terminator."""
    first = ctx.getpass(f"New password for {name}: ")
    try:
        check_for_set(first)
    except PolicyError as exc:
        raise admin_client.CliExit(admin_client.EXIT_USAGE, str(exc)) from None
    second = ctx.getpass("Repeat the password: ")
    if first != second:
        raise admin_client.CliExit(admin_client.EXIT_USAGE, "passwords do not match; nothing changed")
    return first


def _user(args, ctx) -> int:
    if ctx.geteuid() != 0:
        _err(ctx, ROOT_REQUIRED.format(what="accounts.json", who=SERVICE_USER))
        return admin_client.EXIT_USAGE
    if args.action != "list" and not valid_username(args.name):
        _err(ctx, "invalid username (must match ^[a-z][a-z0-9_-]{0,31}$)")
        return admin_client.EXIT_USAGE
    try:
        state_dir, _sessions = _paths(args)
        password = None
        if args.action in ("add", "passwd"):
            password = read_new_password(ctx, args.name)
        service = ctx.getpwnam(SERVICE_USER)
    except admin_client.CliExit as exc:
        _err(ctx, exc.message)
        return exc.code
    except KeyError:
        _err(ctx, f"the {SERVICE_USER} service account does not exist")
        return admin_client.EXIT_USAGE
    except Exception as exc:  # config errors
        _err(ctx, f"cannot read configuration: {exc}")
        return admin_client.EXIT_USAGE

    def child() -> int:
        ctx.ops.setgroups([])
        ctx.ops.setgid(service.pw_gid)
        ctx.ops.setuid(service.pw_uid)
        return _account_work(args, ctx, Path(state_dir), password)

    return ctx.ops.fork_and_wait(child)


LAST_STORE_STEPS: list = []


def _account_work(args, ctx, state_dir: Path, password) -> int:
    path = state_dir / "accounts.json"
    lock_path = state_dir / ".accounts.lock"
    try:
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        _err(ctx, f"cannot open {lock_path}: {exc.strerror}")
        return admin_client.EXIT_USAGE
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            accounts = parse_document(path.read_bytes()) if path.exists() else {}
        except AccountsError:
            _err(ctx, "accounts.json is corrupt; nothing changed (move it aside to start again)")
            return admin_client.EXIT_USAGE
        except OSError as exc:
            _err(ctx, f"cannot read accounts.json: {exc.strerror}")
            return admin_client.EXIT_USAGE
        if args.action == "list":
            if not accounts:
                _out(ctx, "no accounts")
            for name in sorted(accounts):
                entry = accounts[name]
                flag = "disabled" if entry["disabled"] else "enabled"
                _out(ctx, f"{name}\t{entry['role']}\t{flag}")
            return admin_client.EXIT_OK
        name = args.name
        if args.action == "add":
            if name in accounts:
                _err(ctx, f"account {name} already exists; use 'user passwd {name}'")
                return admin_client.EXIT_USAGE
            accounts[name] = {"role": args.role, "hash": hash_password(password), "disabled": False,
                              "created": now_stamp()}
            message = f"account {name} added ({args.role})"
        else:
            if name not in accounts:
                _err(ctx, f"no account named {name}")
                return admin_client.EXIT_USAGE
            if args.action == "passwd":
                accounts[name]["hash"] = hash_password(password)
                message = f"password changed for {name}; existing sessions of {name} end at their next request"
            elif args.action == "disable":
                accounts[name]["disabled"] = True
                message = f"account {name} disabled"
            elif args.action == "enable":
                accounts[name]["disabled"] = False
                message = f"account {name} enabled"
            else:
                del accounts[name]
                message = f"account {name} removed"
        store = Store(path)
        store.replace(render_document(accounts))
        os.chmod(path, 0o600)
        LAST_STORE_STEPS[:] = list(store.steps)
        _out(ctx, message)
        return admin_client.EXIT_OK
    except Exception:
        _err(ctx, "accounts.json could not be written; nothing changed")
        return admin_client.EXIT_USAGE
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


# ---------------------------------------------------------------- client ...

def _render_sessions(clients: dict, timeouts: dict) -> str:
    lines = [
        "# T.A.S.K. task-core login clients (PHASE-2.md section 6.2). No secrets.",
        "# Edited by task-core-admin client allow/remove.",
        "[clients]",
    ]
    for uid in sorted(clients, key=int):
        label = str(clients[uid]).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{int(uid)} = "{label}"')
    if timeouts:
        lines.append("")
        lines.append("[timeouts]")
        for key in ("idle_seconds", "absolute_seconds"):
            if key in timeouts:
                lines.append(f"{key} = {int(timeouts[key])}")
    return "\n".join(lines) + "\n"


def _write_root_file(path: Path, text: str) -> None:
    directory = path.parent
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
        fsync_directory(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _client(args, ctx) -> int:
    if ctx.geteuid() != 0:
        _err(ctx, ROOT_REQUIRED.format(what="sessions.toml", who="root"))
        return admin_client.EXIT_USAGE
    try:
        _state, sessions = _paths(args)
        user = ctx.getpwnam(args.username)
    except KeyError:
        _err(ctx, f"no such user: {args.username}")
        return admin_client.EXIT_USAGE
    except Exception as exc:
        _err(ctx, f"cannot read configuration: {exc}")
        return admin_client.EXIT_USAGE
    clients, timeouts = {}, {}
    if sessions.exists():
        from task_core.config import read_toml

        try:
            document = read_toml(sessions.read_text(encoding="utf-8"))
        except Exception:
            _err(ctx, f"{sessions} is not valid TOML; nothing changed")
            return admin_client.EXIT_USAGE
        clients = {str(key): value for key, value in dict(document.get("clients", {})).items()}
        timeouts = dict(document.get("timeouts", {}))
    uid = str(user.pw_uid)
    if args.action == "allow":
        clients[uid] = args.username
        message = f"{args.username} (uid {uid}) may now call session.login"
    else:
        if uid not in clients:
            _out(ctx, f"{args.username} (uid {uid}) is not in [clients]; nothing to do")
            return admin_client.EXIT_OK
        del clients[uid]
        message = f"{args.username} (uid {uid}) removed from [clients]"
    try:
        _write_root_file(sessions, _render_sessions(clients, timeouts))
    except OSError as exc:
        _err(ctx, f"cannot write {sessions}: {exc.strerror}")
        return admin_client.EXIT_USAGE
    _out(ctx, message)
    if args.action == "allow" and not _in_group(ctx, user):
        _out(ctx, f"{args.username} is not in group {SERVICE_GROUP}, so it cannot reach the socket yet.")
        _out(ctx, f"Run as root (not run by this tool): usermod -aG {SERVICE_GROUP} {args.username}")
        _out(ctx, "then log out and in again.")
    return admin_client.EXIT_OK


def _in_group(ctx, user) -> bool:
    try:
        group = ctx.getgrnam(SERVICE_GROUP)
    except KeyError:
        return False
    return user.pw_gid == group.gr_gid or user.pw_name in group.gr_mem


if __name__ == "__main__":
    sys.exit(main())
