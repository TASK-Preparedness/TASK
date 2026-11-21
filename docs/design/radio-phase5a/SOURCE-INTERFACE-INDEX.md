<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Installed interface signature and provenance index

Static AST inspection only, using /usr/bin/python3; no imported installed code and no sockets. Full function signatures document parameters/defaults. This is an index, not a promise that every internal callable is a public API. Only APIs selected in API-MATRIX.md are integration candidates. Source hashes permit later comparison without redistributing the source archive.

## `/usr/lib/python3/dist-packages/task_core/__init__.py`
SHA-256: `ccba5fc4149a9c837277ef3d7bceb98a408ec3d08ee043b55363aebc57619569`


## `/usr/lib/python3/dist-packages/task_core/__main__.py`
SHA-256: `86b3c84f5476ed7c5d8725879d20dbc979c35fbfc29ed8ddc02dc2344658c334`


## `/usr/lib/python3/dist-packages/task_core/accounts.py`
SHA-256: `205687d984a894f7735b7a03a175368453413a1a5b5019051e9959a975561ff4`

- `valid_username(name) -> bool` — `/usr/lib/python3/dist-packages/task_core/accounts.py:28-29`
- `parse_document(raw: bytes) -> dict` — `/usr/lib/python3/dist-packages/task_core/accounts.py:32-59` — Return {name: entry} or raise AccountsError for any shape problem.
- `render_document(accounts: dict) -> bytes` — `/usr/lib/python3/dist-packages/task_core/accounts.py:62-64`
- `now_stamp() -> str` — `/usr/lib/python3/dist-packages/task_core/accounts.py:67-68`
- `AccountStore.__init__(self, path: Path) -> None` — `/usr/lib/python3/dist-packages/task_core/accounts.py:74-78`
- `AccountStore._stat_key(self)` — `/usr/lib/python3/dist-packages/task_core/accounts.py:80-87`
- `AccountStore.reload_if_changed(self) -> None` — `/usr/lib/python3/dist-packages/task_core/accounts.py:89-94`
- `AccountStore._load(self, key) -> dict` — `/usr/lib/python3/dist-packages/task_core/accounts.py:96-115`
- `AccountStore._preserve_corrupt(self, original: bytes) -> None` — `/usr/lib/python3/dist-packages/task_core/accounts.py:117-132`
- `AccountStore.get(self, name: str)` — `/usr/lib/python3/dist-packages/task_core/accounts.py:134-135`
- `AccountStore.names(self) -> list` — `/usr/lib/python3/dist-packages/task_core/accounts.py:137-138`

## `/usr/lib/python3/dist-packages/task_core/admin.py`
SHA-256: `a4b80516b059a0cc3ce73e962df9da81aeccaa405fe81cab638597446aee88e3`

- `_Ops.__init__(self)` — `/usr/lib/python3/dist-packages/task_core/admin.py:44-47`
- `_Ops.fork_and_wait(self, child) -> int` — `/usr/lib/python3/dist-packages/task_core/admin.py:49-66`
- `_Tty.__init__(self, fd)` — `/usr/lib/python3/dist-packages/task_core/admin.py:72-74`
- `_Tty.write(self, text)` — `/usr/lib/python3/dist-packages/task_core/admin.py:76-77`
- `_Tty.flush(self)` — `/usr/lib/python3/dist-packages/task_core/admin.py:79-80`
- `_Tty.readline(self)` — `/usr/lib/python3/dist-packages/task_core/admin.py:82-83`
- `_Tty.close(self)` — `/usr/lib/python3/dist-packages/task_core/admin.py:85-89`
- `_open_tty()` — `/usr/lib/python3/dist-packages/task_core/admin.py:92-97`
- `_stdin_bytes(limit: int) -> bytes` — `/usr/lib/python3/dist-packages/task_core/admin.py:100-101`
- `Context.__post_init__(self)` — `/usr/lib/python3/dist-packages/task_core/admin.py:117-119`
- `_Parser.error(self, message)` — `/usr/lib/python3/dist-packages/task_core/admin.py:125-128`
- `build_parser() -> argparse.ArgumentParser` — `/usr/lib/python3/dist-packages/task_core/admin.py:131-184`
- `_seq(text)` — `/usr/lib/python3/dist-packages/task_core/admin.py:187-191`
- `main(argv=None, ctx=None) -> int` — `/usr/lib/python3/dist-packages/task_core/admin.py:194-211`
- `_paths(args)` — `/usr/lib/python3/dist-packages/task_core/admin.py:216-227` — state_dir and sessions file from core.toml when present; otherwise the fixed defaults.
- `_err(ctx, text)` — `/usr/lib/python3/dist-packages/task_core/admin.py:232-234`
- `_out(ctx, text)` — `/usr/lib/python3/dist-packages/task_core/admin.py:237-239`
- `read_new_password(ctx, name) -> str` — `/usr/lib/python3/dist-packages/task_core/admin.py:242-252` — Prompt twice with no echo; apply the D4 policy. getpass removes only the line terminator.
- `_user(args, ctx) -> int` — `/usr/lib/python3/dist-packages/task_core/admin.py:255-284`
- `_account_work(args, ctx, state_dir: Path, password) -> int` — `/usr/lib/python3/dist-packages/task_core/admin.py:290-353`
- `_render_sessions(clients: dict, timeouts: dict) -> str` — `/usr/lib/python3/dist-packages/task_core/admin.py:358-373`
- `_write_root_file(path: Path, text: str) -> None` — `/usr/lib/python3/dist-packages/task_core/admin.py:376-389`
- `_client(args, ctx) -> int` — `/usr/lib/python3/dist-packages/task_core/admin.py:392-436`
- `_in_group(ctx, user) -> bool` — `/usr/lib/python3/dist-packages/task_core/admin.py:439-444`

## `/usr/lib/python3/dist-packages/task_core/admin_client.py`
SHA-256: `7f3df13829c3f42a5f450f64d8cf996e51d69b3b136b78abeacba06c23b6c42a`

- `CliExit.__init__(self, code, message=None)` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:47-50`
- `Interrupted.__init__(self, signum)` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:54-56`
- `TaskCoreError.__init__(self, code, message)` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:64-67`
- `unreachable_message(path, exc) -> str` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:70-77`
- `Connection.__init__(self, path, connect_fn=None, clock=time.monotonic)` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:83-90`
- `Connection._connect(path)` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:93-101`
- `Connection.open(self)` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:103-110`
- `Connection.close(self)` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:112-118`
- `Connection.raw(self, body: dict) -> dict` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:120-135`
- `Connection._read(self) -> dict` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:137-144`
- `Connection.call(self, method, params=None, session=None) -> dict` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:146-155`
- `probe_protocol(conn: Connection) -> dict` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:158-169` — core.protocol first; a 0.1.x core answers v1 'unsupported version'.
- `dash(value) -> str` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:174-181`
- `device_name(device) -> str` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:184-185`
- `shared_identity(device) -> bool` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:188-195`
- `slot_line(logical, device) -> str` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:198-203`
- `slots(listing) -> dict` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:206-218`
- `assign_effects(listing, logical, device_id)` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:221-244` — Return (lines, displaced, warnings) exactly as the console's confirmation (8.5).
- `SessionRunner.__init__(self, args, ctx)` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:250-259`
- `SessionRunner.say(self, text='')` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:261-263`
- `SessionRunner.info(self, text='')` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:265-269` — Human-readable progress: stdout normally, stderr with --json (stdout stays pure JSON).
- `SessionRunner.warn(self, text)` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:271-273`
- `SessionRunner.call(self, method, params=None)` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:275-276`
- `SessionRunner.run(self) -> int` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:278-321`
- `SessionRunner._install_signals(self)` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:324-335`
- `SessionRunner._restore_signals(self, previous)` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:337-342`
- `SessionRunner._logout(self)` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:344-362`
- `SessionRunner._read_password(self) -> str` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:365-378`
- `SessionRunner._confirm(self, word: str) -> None` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:380-391`
- `SessionRunner._dispatch(self) -> int` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:394-413`
- `SessionRunner._emit(self, results: dict) -> int` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:415-418`
- `SessionRunner._text(self, line='')` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:420-422`
- `SessionRunner._status(self) -> dict` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:424-448`
- `SessionRunner._devices(self) -> dict` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:450-475`
- `SessionRunner._assignments(self) -> dict` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:477-483`
- `SessionRunner._events(self) -> dict` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:485-501`
- `SessionRunner._require_admin(self, method)` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:503-507`
- `SessionRunner._assign(self) -> int` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:509-546`
- `SessionRunner._unassign(self) -> int` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:548-564`
- `run_session_command(args, ctx) -> int` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:567-574`
- `run_probe(args, ctx) -> int` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:577-604` — probe / probe --public [--stream S]: no session is ever sent.
- `_probe_stream(args, ctx)` — `/usr/lib/python3/dist-packages/task_core/admin_client.py:607-628`

## `/usr/lib/python3/dist-packages/task_core/api.py`
SHA-256: `ff9a5e595cd6ef588195d44d8436c6188704eb7736c26e5dd8f909995d29ea8b`

- `peer_uid(conn: socket.socket) -> int` — `/usr/lib/python3/dist-packages/task_core/api.py:35-39`
- `ok(req_id, result: dict) -> dict` — `/usr/lib/python3/dist-packages/task_core/api.py:42-43`
- `fail(req_id, code: str, message: str) -> dict` — `/usr/lib/python3/dist-packages/task_core/api.py:46-52`
- `Server.__init__(self, core, idle_timeout: float=IDLE_TIMEOUT, peer_uid_fn=None, extra_methods=None) -> None` — `/usr/lib/python3/dist-packages/task_core/api.py:56-68`
- `Server.start(self, path: str) -> None` — `/usr/lib/python3/dist-packages/task_core/api.py:70-85`
- `Server.stop(self) -> None` — `/usr/lib/python3/dist-packages/task_core/api.py:87-96`
- `Server.handle_line(self, line: bytes, uid: int) -> dict` — `/usr/lib/python3/dist-packages/task_core/api.py:98-130`
- `Server._dispatch(self, method: str, params: dict, uid: int) -> dict` — `/usr/lib/python3/dist-packages/task_core/api.py:132-146`
- `Server._accept_loop(self) -> None` — `/usr/lib/python3/dist-packages/task_core/api.py:148-169`
- `Server._serve_client(self, conn: socket.socket) -> None` — `/usr/lib/python3/dist-packages/task_core/api.py:171-185`
- `Server._client_loop(self, conn: socket.socket) -> None` — `/usr/lib/python3/dist-packages/task_core/api.py:187-225`
- `Server._send(self, conn: socket.socket, payload: dict) -> bool` — `/usr/lib/python3/dist-packages/task_core/api.py:227-237`
- `Server._become_stream(self, conn: socket.socket, response: dict, subscriber, buffer: bytes) -> None` — `/usr/lib/python3/dist-packages/task_core/api.py:239-262` — v2 events.subscribe succeeded: the connection is a stream from now on (section 5.8).
- `_v2_payload(line: bytes)` — `/usr/lib/python3/dist-packages/task_core/api.py:265-274` — Return the parsed request if it is protocol v2 (an int "v" equal to 2), else None.
- `_try_group(path: str) -> None` — `/usr/lib/python3/dist-packages/task_core/api.py:277-286`

## `/usr/lib/python3/dist-packages/task_core/auth.py`
SHA-256: `70c99813c169a206d46f5f4dd6ce28a21358f7092b1994f6eaff3b31e737da05`

- `Auth.__init__(self, mapping: dict[int, str]) -> None` — `/usr/lib/python3/dist-packages/task_core/auth.py:17-18`
- `Auth.role_for(self, uid: int) -> str` — `/usr/lib/python3/dist-packages/task_core/auth.py:20-24`
- `Auth.allows(self, uid: int, minimum: str) -> bool` — `/usr/lib/python3/dist-packages/task_core/auth.py:26-27`
- `load_auth(path: Path) -> Auth` — `/usr/lib/python3/dist-packages/task_core/auth.py:30-54`

## `/usr/lib/python3/dist-packages/task_core/bus.py`
SHA-256: `4c6330c31f4e4fc4e9cf13a4e725f1136f8fc940483ffeae6111f627f98da6cd`

- `_event_id() -> str` — `/usr/lib/python3/dist-packages/task_core/bus.py:28-29`
- `Bus.__init__(self) -> None` — `/usr/lib/python3/dist-packages/task_core/bus.py:42-49`
- `Bus.subscribe(self, callback) -> None` — `/usr/lib/python3/dist-packages/task_core/bus.py:51-53`
- `Bus.add_listener(self, callback) -> None` — `/usr/lib/python3/dist-packages/task_core/bus.py:55-57`
- `Bus.remove_listener(self, callback) -> None` — `/usr/lib/python3/dist-packages/task_core/bus.py:59-62`
- `Bus.publish(self, topic: str, source: str, data: dict | None=None) -> dict` — `/usr/lib/python3/dist-packages/task_core/bus.py:64-91`
- `Bus.recent(self) -> list` — `/usr/lib/python3/dist-packages/task_core/bus.py:93-95`
- `Bus.recent_v2(self) -> list` — `/usr/lib/python3/dist-packages/task_core/bus.py:97-99`
- `Bus.last_seq(self) -> int` — `/usr/lib/python3/dist-packages/task_core/bus.py:101-103`
- `Bus.snapshot_and_listen(self, callback) -> int` — `/usr/lib/python3/dist-packages/task_core/bus.py:105-109` — Register a stream listener and return the seq it starts after.

## `/usr/lib/python3/dist-packages/task_core/capabilities.py`
SHA-256: `6fb45644aaa14b2c1e0e34d8d1017a80284ba96d479cd0c334ab4ad041afddbd`

- `Registry.__init__(self, bus) -> None` — `/usr/lib/python3/dist-packages/task_core/capabilities.py:24-28`
- `Registry.kind(self, name: str) -> str` — `/usr/lib/python3/dist-packages/task_core/capabilities.py:30-33`
- `Registry.recompute(self, connected_logicals: set[str]) -> dict[str, str]` — `/usr/lib/python3/dist-packages/task_core/capabilities.py:35-63`
- `Registry.mark_live(self) -> None` — `/usr/lib/python3/dist-packages/task_core/capabilities.py:65-66`
- `Registry.public(self) -> dict` — `/usr/lib/python3/dist-packages/task_core/capabilities.py:68-74`

## `/usr/lib/python3/dist-packages/task_core/config.py`
SHA-256: `a0d750ca5cdc85a7675a31451bfdb235b04c876d8207aee05b6b9678829d6929`

- `read_toml(text: str) -> dict` — `/usr/lib/python3/dist-packages/task_core/config.py:10-18`
- `validate_socket(value) -> str` — `/usr/lib/python3/dist-packages/task_core/config.py:21-31`
- `load_config(path: Path) -> Config` — `/usr/lib/python3/dist-packages/task_core/config.py:44-70`
- `_dir_value(value, label: str) -> Path` — `/usr/lib/python3/dist-packages/task_core/config.py:73-76`

## `/usr/lib/python3/dist-packages/task_core/devices.py`
SHA-256: `60c0e5af37c76cfb68d6b4bad7c1a439c36044e2329754e333588a9bfa9c37c2`

- `is_real_serial(serial: str | None) -> bool` — `/usr/lib/python3/dist-packages/task_core/devices.py:26-32`
- `make_id(key: str) -> str` — `/usr/lib/python3/dist-packages/task_core/devices.py:35-36`
- `identity_for(raw: 'RawDevice') -> tuple[str, bool]` — `/usr/lib/python3/dist-packages/task_core/devices.py:39-55` — Return (identity key, stable). Devnode is never the key.
- `DeviceRecord.public(self) -> dict` — `/usr/lib/python3/dist-packages/task_core/devices.py:91-108`
- `load_rules(path) -> list` — `/usr/lib/python3/dist-packages/task_core/devices.py:111-151`
- `classify(raw: RawDevice, rules: list) -> tuple[str, list]` — `/usr/lib/python3/dist-packages/task_core/devices.py:154-165`
- `Manager.__init__(self, store: Store, rules: list, bus) -> None` — `/usr/lib/python3/dist-packages/task_core/devices.py:171-179`
- `Manager._install_placeholders(self) -> None` — `/usr/lib/python3/dist-packages/task_core/devices.py:181-200`
- `Manager.apply_enumerated(self, raws: list[RawDevice]) -> None` — `/usr/lib/python3/dist-packages/task_core/devices.py:202-206`
- `Manager.appear(self, raw: RawDevice) -> None` — `/usr/lib/python3/dist-packages/task_core/devices.py:208-211`
- `Manager.disappear(self, raw: RawDevice, replaced: bool=False) -> None` — `/usr/lib/python3/dist-packages/task_core/devices.py:213-242` — Mark a device disconnected and announce it once.
- `Manager.change(self, raw: RawDevice) -> None` — `/usr/lib/python3/dist-packages/task_core/devices.py:244-247`
- `Manager.counts(self) -> dict` — `/usr/lib/python3/dist-packages/task_core/devices.py:249-254` — device.counts: over exactly the records device.list returns.
- `Manager._publish_counts(self) -> None` — `/usr/lib/python3/dist-packages/task_core/devices.py:256-262`
- `Manager.displacement(self, logical: str, device_id: str) -> list` — `/usr/lib/python3/dist-packages/task_core/devices.py:264-274` — What a Phase 1 assign of device_id to logical would take away (section 5.10).
- `Manager._upsert(self, raw: RawDevice, emit: bool) -> None` — `/usr/lib/python3/dist-packages/task_core/devices.py:276-334`
- `Manager._saved(self, device_id: str) -> tuple[str | None, str | None]` — `/usr/lib/python3/dist-packages/task_core/devices.py:336-340`
- `Manager.connected_logicals(self) -> set[str]` — `/usr/lib/python3/dist-packages/task_core/devices.py:342-348`
- `Manager.list_public(self) -> dict` — `/usr/lib/python3/dist-packages/task_core/devices.py:350-354`
- `Manager.get_public(self, params: dict) -> dict` — `/usr/lib/python3/dist-packages/task_core/devices.py:356-369`
- `Manager.assign(self, logical: str, device_id: str, alias: str | None, v2: bool=False, confirm_displace: bool=False) -> dict` — `/usr/lib/python3/dist-packages/task_core/devices.py:371-418` — Phase 1 assign. With v2=True, a displacement needs confirm_displace (section 5.10).
- `Manager.unassign(self, logical: str) -> dict` — `/usr/lib/python3/dist-packages/task_core/devices.py:420-439`
- `Manager._by_logical(self, logical: str) -> DeviceRecord | None` — `/usr/lib/python3/dist-packages/task_core/devices.py:441-445`
- `Manager._assignment_view(self) -> dict` — `/usr/lib/python3/dist-packages/task_core/devices.py:447-456`
- `Manager._write(self) -> None` — `/usr/lib/python3/dist-packages/task_core/devices.py:458-467`
- `_displace_message(displaced: list) -> str` — `/usr/lib/python3/dist-packages/task_core/devices.py:470-471`
- `_lower_or_none(value)` — `/usr/lib/python3/dist-packages/task_core/devices.py:474-477`

## `/usr/lib/python3/dist-packages/task_core/enumerator.py`
SHA-256: `a9c12f24167b3c43164be6e13f181b205e039c6742e3eeaac9de9c335c08c12c`

- `EnumState.__init__(self) -> None` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:41-46`
- `EnumState.known_paths(self) -> set` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:48-49`
- `NullEnumerator.start(self, on_appear, on_disappear, on_change) -> list` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:53-54`
- `NullEnumerator.stop(self) -> None` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:56-57`
- `NullEnumerator.status(self) -> dict` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:59-60`
- `UdevEnumerator.__init__(self, pyudev_module=None, rescan_interval: float=RESCAN_INTERVAL, confirm_delay: float=CONFIRM_DELAY, degraded_interval: float=DEGRADED_INTERVAL, restart_backoff: tuple=RESTART_BACKOFF, poll_timeout: float=POLL_TIMEOUT) -> None` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:72-107`
- `UdevEnumerator.start(self, on_appear, on_disappear, on_change) -> list` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:111-133`
- `UdevEnumerator.begin(self) -> None` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:135-140` — Core has applied the list start() returned: deliver live events now.
- `UdevEnumerator.stop(self) -> None` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:142-146`
- `UdevEnumerator.status(self) -> dict` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:148-154` — Hot-plug monitor state: running | degraded | restarting | stopped.
- `UdevEnumerator.join(self, timeout: float | None=None) -> None` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:156-158`
- `UdevEnumerator._open_monitor(self)` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:162-170`
- `UdevEnumerator._close_monitor(self) -> None` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:172-181`
- `UdevEnumerator._watch(self) -> None` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:183-240`
- `UdevEnumerator._backoff(self, failures: int) -> float` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:242-244`
- `UdevEnumerator._scan(self, skipped: set | None=None) -> list` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:248-270` — Scan udev like the 0.1.1 startup scan. With skipped (resync), devices
- `UdevEnumerator._resync(self, confirm: bool, pending=None)` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:272-309` — Apply the difference between udev's device list and what was announced.
- `UdevEnumerator._stored(self, sys_path)` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:311-314`
- `UdevEnumerator._dispatch(self, device) -> None` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:318-350`
- `UdevEnumerator._run(self, ops, raw, action) -> None` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:352-366`
- `UdevEnumerator._set_status(self, **fields) -> None` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:370-372`
- `UdevEnumerator._bump(self, name: str, amount: int=1) -> None` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:374-376`
- `_initialized(device) -> bool` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:379-383`
- `_old_sys_path(device)` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:386-391`
- `_initial_status() -> dict` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:394-396`
- `_error_name(exc: BaseException) -> str` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:399-403`
- `choose_present(items: list[tuple]) -> list[tuple]` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:406-423` — Drop a USB parent when its serial interface is already present.
- `seed_state(chosen: list[tuple]) -> EnumState` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:426-435`
- `apply_event(state: EnumState, raw: RawDevice, sys_path, parent_path, action) -> list` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:438-484` — Return ("appear"|"change"|"disappear", raw) operations. Updates state.
- `_action_kind(action) -> str` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:487-492`
- `_scan_item(device)` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:495-501`
- `_from_udev(device) -> RawDevice | None` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:504-537`
- `_tty_is_usb(device) -> bool` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:540-549` — True only when udev or sysfs says this tty is a USB device.
- `_usb_parent(device)` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:552-559`
- `_sysfs_text(device, name: str) -> str | None` — `/usr/lib/python3/dist-packages/task_core/enumerator.py:562-572`

## `/usr/lib/python3/dist-packages/task_core/errors.py`
SHA-256: `d04ae40d085779ebca4486cb8d4d9dc39f11b869c45b2e484d89c0d79d5332be`

- `ApiError.__init__(self, code: str, message: str) -> None` — `/usr/lib/python3/dist-packages/task_core/errors.py:12-15`

## `/usr/lib/python3/dist-packages/task_core/exclusion.py`
SHA-256: `e9fce2c96b3e0e93877cbf9164eb6dab92252a356b57662d68068d75c413db2d`

- `StateLock.__init__(self, state_dir: Path)` — `/usr/lib/python3/dist-packages/task_core/exclusion.py:29-31`
- `StateLock.acquire(self) -> 'StateLock'` — `/usr/lib/python3/dist-packages/task_core/exclusion.py:33-44`
- `StateLock.release(self) -> None` — `/usr/lib/python3/dist-packages/task_core/exclusion.py:46-52`
- `StateLock.__enter__(self)` — `/usr/lib/python3/dist-packages/task_core/exclusion.py:54-55`
- `StateLock.__exit__(self, *exc)` — `/usr/lib/python3/dist-packages/task_core/exclusion.py:57-58`
- `legacy_processes(proc_root: Path=Path('/proc'), self_pid: int=None) -> list` — `/usr/lib/python3/dist-packages/task_core/exclusion.py:61-81` — PIDs whose command line names the legacy rain-core (rain_core/rain-core).
- `legacy_socket_live(own_socket: str, legacy_socket: str=LEGACY_SOCKET) -> bool` — `/usr/lib/python3/dist-packages/task_core/exclusion.py:84-102` — True if something answers on the legacy socket and it is not our own socket.
- `guard(state_dir: Path, own_socket: str, *, proc_root: Path=Path('/proc'), legacy_socket: str=LEGACY_SOCKET) -> StateLock` — `/usr/lib/python3/dist-packages/task_core/exclusion.py:105-118` — Take the state lock and refuse if a legacy rain-core is active. Caller keeps the lock.

## `/usr/lib/python3/dist-packages/task_core/main.py`
SHA-256: `2583fe236f9615012b3c2f735b05fb3c4df2c987617fb03d7f113b69118f035c`

- `Core.__init__(self, config: Config, enumerator_factory=None, euid_fn=None, idle_timeout: float=None, peer_uid_fn=None, extra_methods=None, clock=None, heartbeat_interval=None, stream_write_timeout=None, stream_check_interval=None) -> None` — `/usr/lib/python3/dist-packages/task_core/main.py:43-80`
- `Core.open(self) -> None` — `/usr/lib/python3/dist-packages/task_core/main.py:82-131`
- `Core.close(self) -> None` — `/usr/lib/python3/dist-packages/task_core/main.py:133-145`
- `Core.handle_v2(self, payload: dict, uid: int)` — `/usr/lib/python3/dist-packages/task_core/main.py:147-149` — Protocol v2 entry (section 5). Returns (response, subscriber-or-None).
- `Core._check_state_owner(self) -> None` — `/usr/lib/python3/dist-packages/task_core/main.py:151-158`
- `Core.wait(self) -> None` — `/usr/lib/python3/dist-packages/task_core/main.py:160-168`
- `Core.call(self, method: str, params: dict) -> dict` — `/usr/lib/python3/dist-packages/task_core/main.py:170-195`
- `Core._health(self) -> dict` — `/usr/lib/python3/dist-packages/task_core/main.py:197-206`
- `Core._assign(self, params: dict) -> dict` — `/usr/lib/python3/dist-packages/task_core/main.py:208-221`
- `Core.hotplug_status(self) -> dict` — `/usr/lib/python3/dist-packages/task_core/main.py:223-232` — Hot-plug monitor state for v2 core.health (H1). Never identifying.
- `Core._on_event(self, event: dict) -> None` — `/usr/lib/python3/dist-packages/task_core/main.py:234-241`
- `Core._refresh(self, announce: bool) -> None` — `/usr/lib/python3/dist-packages/task_core/main.py:243-246`
- `Core._open_enumerator(self)` — `/usr/lib/python3/dist-packages/task_core/main.py:248-253`
- `Core._rules_path(self) -> Path` — `/usr/lib/python3/dist-packages/task_core/main.py:255-259`
- `main(argv=None) -> int` — `/usr/lib/python3/dist-packages/task_core/main.py:262-295`

## `/usr/lib/python3/dist-packages/task_core/modules.py`
SHA-256: `caa85a9cf2fddafddac6b6d5edffaae076d0c10203d006d626e7cbc46ecb1bf7`

- `Manifest.public(self) -> dict` — `/usr/lib/python3/dist-packages/task_core/modules.py:37-50`
- `load_manifests(directory: Path, bus) -> list[Manifest]` — `/usr/lib/python3/dist-packages/task_core/modules.py:53-70`
- `recompute_states(manifests: list[Manifest], capability_status: dict, bus, announce: bool) -> None` — `/usr/lib/python3/dist-packages/task_core/modules.py:73-94`
- `_state_for(manifest: Manifest, by_id: dict, states: dict, capability_status: dict) -> str` — `/usr/lib/python3/dist-packages/task_core/modules.py:97-107`
- `_reject_cycles(manifests: list[Manifest], bus) -> None` — `/usr/lib/python3/dist-packages/task_core/modules.py:110-143`
- `_read_one(path: Path) -> Manifest` — `/usr/lib/python3/dist-packages/task_core/modules.py:146-183`
- `_validate(document: dict, stem: str, path: Path) -> Manifest` — `/usr/lib/python3/dist-packages/task_core/modules.py:186-233`
- `_string_list(value, label: str) -> list` — `/usr/lib/python3/dist-packages/task_core/modules.py:236-239`
- `_permissions(value) -> dict` — `/usr/lib/python3/dist-packages/task_core/modules.py:242-251`

## `/usr/lib/python3/dist-packages/task_core/passwords.py`
SHA-256: `a6a9f6afb7efe0a0839155446e43f39133b1a12aadf2d9c694d1a0d093c8c6a4`

- `normalize(password: str) -> str` — `/usr/lib/python3/dist-packages/task_core/passwords.py:37-38`
- `length_ok(password: str) -> bool` — `/usr/lib/python3/dist-packages/task_core/passwords.py:41-42`
- `has_control(password: str) -> bool` — `/usr/lib/python3/dist-packages/task_core/passwords.py:45-46`
- `check_for_set(password: str) -> str` — `/usr/lib/python3/dist-packages/task_core/passwords.py:49-58` — Return the NFC password to store, or raise PolicyError (set time only).
- `_derive(normalized: str, salt: bytes) -> bytes` — `/usr/lib/python3/dist-packages/task_core/passwords.py:61-71`
- `_b64(data: bytes) -> str` — `/usr/lib/python3/dist-packages/task_core/passwords.py:74-75`
- `hash_password(password: str) -> str` — `/usr/lib/python3/dist-packages/task_core/passwords.py:78-81`
- `parse_hash(stored: str)` — `/usr/lib/python3/dist-packages/task_core/passwords.py:84-98`
- `valid_hash_format(stored) -> bool` — `/usr/lib/python3/dist-packages/task_core/passwords.py:101-102`
- `dummy_verify() -> bool` — `/usr/lib/python3/dist-packages/task_core/passwords.py:108-111` — Spend one scrypt so a missing account costs the same as a real one.
- `verify(password, stored) -> bool` — `/usr/lib/python3/dist-packages/task_core/passwords.py:114-123` — Login-time check. Never raises for bad input; out-of-policy costs a dummy scrypt.

## `/usr/lib/python3/dist-packages/task_core/persist.py`
SHA-256: `76278a47c18bd4bb2ef73d965b8cb54ca3661c7df8e04321461fdc4a5a4b6a2c`

- `reset_directory_fsync_warning() -> None` — `/usr/lib/python3/dist-packages/task_core/persist.py:18-20`
- `fsync_directory(directory: Path) -> None` — `/usr/lib/python3/dist-packages/task_core/persist.py:23-48` — Fsync a directory after rename.
- `Store.__init__(self, path: Path) -> None` — `/usr/lib/python3/dist-packages/task_core/persist.py:54-57`
- `Store.load_assignments(self) -> tuple[dict, bool]` — `/usr/lib/python3/dist-packages/task_core/persist.py:59-70` — Return (assignments, ok). A corrupt file is preserved as evidence.
- `Store.save_assignments(self, assignments: dict) -> None` — `/usr/lib/python3/dist-packages/task_core/persist.py:72-75`
- `Store.replace(self, payload: bytes) -> None` — `/usr/lib/python3/dist-packages/task_core/persist.py:77-115`
- `Store._preserve_corrupt(self, original: bytes) -> None` — `/usr/lib/python3/dist-packages/task_core/persist.py:117-132`
- `_valid_assignments(document) -> dict` — `/usr/lib/python3/dist-packages/task_core/persist.py:135-157`
- `_device_id_ok(value: str) -> bool` — `/usr/lib/python3/dist-packages/task_core/persist.py:160-164`

## `/usr/lib/python3/dist-packages/task_core/protocol_v2.py`
SHA-256: `ee42d6725865c29836dfe8844ebe7005494ac841a07d700dc3f953e2b42dab26`

- `ok(req_id, result: dict) -> dict` — `/usr/lib/python3/dist-packages/task_core/protocol_v2.py:42-43`
- `fail(req_id, code: str, message: str) -> dict` — `/usr/lib/python3/dist-packages/task_core/protocol_v2.py:46-47`
- `is_v2(payload) -> bool` — `/usr/lib/python3/dist-packages/task_core/protocol_v2.py:50-54`
- `V2Handler.__init__(self, core) -> None` — `/usr/lib/python3/dist-packages/task_core/protocol_v2.py:58-59`
- `V2Handler.handle(self, payload: dict, uid: int)` — `/usr/lib/python3/dist-packages/task_core/protocol_v2.py:61-88` — Return (response, subscriber-or-None).
- `V2Handler._dispatch(self, method, params, payload, uid, stream)` — `/usr/lib/python3/dist-packages/task_core/protocol_v2.py:90-135`
- `V2Handler._assign(self, params: dict) -> dict` — `/usr/lib/python3/dist-packages/task_core/protocol_v2.py:137-153`
- `V2Handler._since(self, params: dict, role: str) -> dict` — `/usr/lib/python3/dist-packages/task_core/protocol_v2.py:155-169`
- `V2Handler._subscribe(self, params: dict, role: str, session, stream: list) -> dict` — `/usr/lib/python3/dist-packages/task_core/protocol_v2.py:171-180`

## `/usr/lib/python3/dist-packages/task_core/public_view.py`
SHA-256: `4c8a6c47f33a52d08b3b770359b0c832c102fb4b4d36910939749060801eb491`

- `event_allowed(role: str, topic: str) -> bool` — `/usr/lib/python3/dist-packages/task_core/public_view.py:13-16`
- `filter_events(role: str, events: list) -> list` — `/usr/lib/python3/dist-packages/task_core/public_view.py:19-20`
- `redact_module_list(result: dict) -> dict` — `/usr/lib/python3/dist-packages/task_core/public_view.py:23-29` — Public module.list: every module without logical_devices, nothing else changed.

## `/usr/lib/python3/dist-packages/task_core/sessions.py`
SHA-256: `0bd07d78bd219cc0af4761fcbdd7816163149cd764e2240d41df05b70c70c119`

- `_token_hash(token: str) -> str` — `/usr/lib/python3/dist-packages/task_core/sessions.py:37-38`
- `SessionsConfig.__init__(self, path: Path) -> None` — `/usr/lib/python3/dist-packages/task_core/sessions.py:44-50`
- `SessionsConfig._stat_key(self)` — `/usr/lib/python3/dist-packages/task_core/sessions.py:52-57`
- `SessionsConfig.reload_if_changed(self) -> None` — `/usr/lib/python3/dist-packages/task_core/sessions.py:59-95`
- `SessionsConfig._timeout(table, key, default)` — `/usr/lib/python3/dist-packages/task_core/sessions.py:98-105`
- `SessionsConfig.allows(self, uid: int) -> bool` — `/usr/lib/python3/dist-packages/task_core/sessions.py:107-108`
- `RateLimiter.__init__(self, clock) -> None` — `/usr/lib/python3/dist-packages/task_core/sessions.py:114-116`
- `RateLimiter.remaining(self, key) -> float` — `/usr/lib/python3/dist-packages/task_core/sessions.py:118-122`
- `RateLimiter.failure(self, key) -> None` — `/usr/lib/python3/dist-packages/task_core/sessions.py:124-129`
- `RateLimiter.reset(self, key) -> None` — `/usr/lib/python3/dist-packages/task_core/sessions.py:131-132`
- `Session.__init__(self, token_hash, uid, username, role, now, account_hash)` — `/usr/lib/python3/dist-packages/task_core/sessions.py:138-146`
- `SessionManager.__init__(self, accounts_path: Path, sessions_path: Path, clock=None) -> None` — `/usr/lib/python3/dist-packages/task_core/sessions.py:150-157`
- `SessionManager.login(self, uid: int, username, secret) -> dict` — `/usr/lib/python3/dist-packages/task_core/sessions.py:160-197`
- `SessionManager.logout(self, session: Session) -> dict` — `/usr/lib/python3/dist-packages/task_core/sessions.py:199-202`
- `SessionManager.resolve(self, token, uid: int, touch: bool=True) -> Session` — `/usr/lib/python3/dist-packages/task_core/sessions.py:205-219` — Return the live session for token+uid or raise unauthenticated.
- `SessionManager.check(self, session: Session) -> bool` — `/usr/lib/python3/dist-packages/task_core/sessions.py:221-226` — Stream-side check; never refreshes the idle timer.
- `SessionManager._still_valid(self, session: Session) -> bool` — `/usr/lib/python3/dist-packages/task_core/sessions.py:228-246`
- `SessionManager.info(self, session: Session) -> dict` — `/usr/lib/python3/dist-packages/task_core/sessions.py:248-255`
- `SessionManager.add_end_hook(self, session: Session, callback) -> None` — `/usr/lib/python3/dist-packages/task_core/sessions.py:257-259`
- `SessionManager.remove_end_hook(self, session: Session, callback) -> None` — `/usr/lib/python3/dist-packages/task_core/sessions.py:261-264`
- `SessionManager._end(self, session: Session, reason: str) -> None` — `/usr/lib/python3/dist-packages/task_core/sessions.py:266-275`
- `SessionManager.sweep(self) -> None` — `/usr/lib/python3/dist-packages/task_core/sessions.py:277-281` — Expire idle/absolute sessions (called periodically by stream senders).
- `SessionManager.count(self) -> int` — `/usr/lib/python3/dist-packages/task_core/sessions.py:283-285`

## `/usr/lib/python3/dist-packages/task_core/socketpath.py`
SHA-256: `2e9e38746b15c8f223baedfb1b561e890ea259c7d0ec4601182bc321af907e07`

- `resolve_socket(explicit=None, environ=None, exists=os.path.exists) -> str` — `/usr/lib/python3/dist-packages/task_core/socketpath.py:15-25`

## `/usr/lib/python3/dist-packages/task_core/stream.py`
SHA-256: `d69384f8e3a4bb0068e3e2f094779daf0c71b8f3c079b1ec7f937ca034a3f5a5`

- `_now_text() -> str` — `/usr/lib/python3/dist-packages/task_core/stream.py:28-29`
- `_encode(frame: dict) -> bytes` — `/usr/lib/python3/dist-packages/task_core/stream.py:32-33`
- `Subscriber.__init__(self, hub, role, topics, session) -> None` — `/usr/lib/python3/dist-packages/task_core/stream.py:37-50`
- `Subscriber.offer(self, event: dict) -> None` — `/usr/lib/python3/dist-packages/task_core/stream.py:53-66`
- `Subscriber.end(self, reason: str) -> None` — `/usr/lib/python3/dist-packages/task_core/stream.py:68-72`
- `Subscriber.on_session_end(self, _why: str) -> None` — `/usr/lib/python3/dist-packages/task_core/stream.py:74-75`
- `Subscriber.start(self, conn: socket.socket) -> None` — `/usr/lib/python3/dist-packages/task_core/stream.py:77-81`
- `Subscriber._sender(self) -> None` — `/usr/lib/python3/dist-packages/task_core/stream.py:83-134`
- `Subscriber._write(self, frame: dict) -> bool` — `/usr/lib/python3/dist-packages/task_core/stream.py:136-137`
- `Subscriber._write_many(self, frames: list) -> bool` — `/usr/lib/python3/dist-packages/task_core/stream.py:139-148`
- `Subscriber.close(self) -> None` — `/usr/lib/python3/dist-packages/task_core/stream.py:150-160`
- `Subscriber.closed(self) -> bool` — `/usr/lib/python3/dist-packages/task_core/stream.py:163-164`
- `Subscriber.join(self, timeout: float) -> None` — `/usr/lib/python3/dist-packages/task_core/stream.py:166-168`
- `StreamHub.__init__(self, bus, sessions, heartbeat_interval=None, write_timeout=None, check_interval=None, max_streams=MAX_STREAMS) -> None` — `/usr/lib/python3/dist-packages/task_core/stream.py:172-182`
- `StreamHub.open(self, role, topics, session)` — `/usr/lib/python3/dist-packages/task_core/stream.py:184-195` — Reserve a slot and attach to the bus. Returns (subscriber, seq) or None if busy.
- `StreamHub.release(self, subscriber) -> None` — `/usr/lib/python3/dist-packages/task_core/stream.py:197-203`
- `StreamHub.active(self) -> int` — `/usr/lib/python3/dist-packages/task_core/stream.py:205-207`
- `StreamHub.shutdown(self) -> None` — `/usr/lib/python3/dist-packages/task_core/stream.py:209-216`

## `/usr/lib/python3/dist-packages/task_comms/__init__.py`
SHA-256: `3632a79f7c5d9139304464ef2adfaea829ab7cc3d38b99ebca415777623415eb`


## `/usr/lib/python3/dist-packages/task_comms/aprs.py`
SHA-256: `71f7c2e0e8adc87b0d60f5a29e72103426db49342e32b9f2931b6c32a8d092bb`

- `KissDecoder.__init__(self)` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:21-24`
- `KissDecoder.feed(self, data: bytes)` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:26-46`
- `KissDecoder._unescape(data: bytes)` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:49-65`
- `Address.__str__(self)` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:76-78`
- `Frame.is_ui(self)` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:91-92`
- `Frame.header(self)` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:94-97`
- `_addr(chunk: bytes)` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:104-114`
- `decode_ax25(data: bytes) -> Frame` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:117-140`
- `AprsPacket.summary(self)` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:164-177` — Decoded content (the packet type is shown separately).
- `_lat(s: str)` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:180-187`
- `_lon(s: str)` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:190-197`
- `_b91(s: str)` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:200-207`
- `_position(p: AprsPacket, body: str)` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:210-228` — Uncompressed or compressed position at the start of body; returns the comment.
- `format_weather(wx: dict) -> str` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:231-246` — Human text for parse_weather() values, in the units the station sent (APRS: mph, °F).
- `parse_weather(text: str)` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:249-269` — Common APRS weather fields: wind dir/speed (mph), gust (mph), temperature (°F), rain,
- `_mic_e(p: AprsPacket, dest: str, info: bytes)` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:272-306`
- `parse_aprs(frame: Frame, port: int=0, now: float=None) -> AprsPacket` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:309-360`
- `parse_callsign(text: str) -> Address` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:370-378`
- `_enc_addr(a: Address, last: bool, h_bit: bool=False, cr: bool=False) -> bytes` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:381-384`
- `encode_ax25(source: Address, dest: Address, path=(), info: bytes=b'') -> bytes` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:387-394`
- `kiss_frame(payload: bytes, port: int=0) -> bytes` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:397-406`
- `check_text(text: str, limit: int, what: str)` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:409-416`
- `message_info(addressee: str, text: str, msg_id: str=None) -> str` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:419-429` — APRS 1.0.1 ch.14 message: ':ADDRESSEE:text{id'.
- `ack_info(addressee: str, msg_id: str, reject: bool=False) -> str` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:432-433`
- `_fmt_lat(lat)` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:436-441`
- `_fmt_lon(lon)` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:444-449`
- `position_info(lat: float, lon: float, symbol: str='/>', comment: str='', messaging: bool=True) -> str` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:452-458` — Uncompressed position without timestamp ('=' if messaging capable).
- `parse_ack(p: 'AprsPacket')` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:461-469` — ('ack'|'rej', id) if a message packet is an ack/rej, else None.
- `message_id_of(p: 'AprsPacket')` — `/usr/lib/python3/dist-packages/task_comms/aprs.py:472-476`

## `/usr/lib/python3/dist-packages/task_comms/audit.py`
SHA-256: `33b5ef675c6afcba6bc038488e6ab215bd7f8aee82b8f101a9138c16463099ce`

- `_digest(prev: str, rec: dict) -> str` — `/usr/lib/python3/dist-packages/task_comms/audit.py:20-22`
- `payload_digest(payload) -> dict` — `/usr/lib/python3/dist-packages/task_comms/audit.py:25-27`
- `AuditLog.__init__(self, path: Path, clock=time.time)` — `/usr/lib/python3/dist-packages/task_comms/audit.py:31-34`
- `AuditLog._tail(self)` — `/usr/lib/python3/dist-packages/task_comms/audit.py:36-47`
- `AuditLog.append(self, **fields) -> dict` — `/usr/lib/python3/dist-packages/task_comms/audit.py:49-61`
- `AuditLog.verify(self)` — `/usr/lib/python3/dist-packages/task_comms/audit.py:63-79` — (ok, count, problem).

## `/usr/lib/python3/dist-packages/task_comms/auth.py`
SHA-256: `142fa52bc37baa45e7e4313f1d317d2efaaf004ceca8a69805fb14470a15749a`

- `SessionGate.__init__(self, client, clock=time.monotonic, idle_lock_s=None)` — `/usr/lib/python3/dist-packages/task_comms/auth.py:15-21`
- `SessionGate.unlocked(self)` — `/usr/lib/python3/dist-packages/task_comms/auth.py:24-31`
- `SessionGate.sign_in(self, username, secret)` — `/usr/lib/python3/dist-packages/task_comms/auth.py:33-36`
- `SessionGate.touch(self)` — `/usr/lib/python3/dist-packages/task_comms/auth.py:38-39`
- `SessionGate.require(self, role='operator')` — `/usr/lib/python3/dist-packages/task_comms/auth.py:41-47`
- `SessionGate.session_ended(self, reason='session-ended')` — `/usr/lib/python3/dist-packages/task_comms/auth.py:49-51`
- `SessionGate._end_locked(self, reason)` — `/usr/lib/python3/dist-packages/task_comms/auth.py:53-57`
- `SessionGate.sign_out(self)` — `/usr/lib/python3/dist-packages/task_comms/auth.py:59-62`

## `/usr/lib/python3/dist-packages/task_comms/bridge.py`
SHA-256: `bb31fe4ef13a0be5a161f77482de31ab65aa547870420125252f658fab6aecb9`

- `Bridge.forward(self, *_args, **_kwargs)` — `/usr/lib/python3/dist-packages/task_comms/bridge.py:16-17`

## `/usr/lib/python3/dist-packages/task_comms/core.py`
SHA-256: `4c3be3a583a705ac50d003e18194cda08bed882ddeb0188fcce57c5a5e601684`

- `resolve_socket(explicit=None, environ=None, exists=os.path.exists)` — `/usr/lib/python3/dist-packages/task_comms/core.py:20-29`
- `CoreError.__init__(self, code, message='')` — `/usr/lib/python3/dist-packages/task_comms/core.py:33-35`
- `CoreClient.__init__(self, path=None, timeout=3.0)` — `/usr/lib/python3/dist-packages/task_comms/core.py:39-45`
- `CoreClient.__repr__(self)` — `/usr/lib/python3/dist-packages/task_comms/core.py:47-48`
- `CoreClient.call(self, method, params=None, session=True)` — `/usr/lib/python3/dist-packages/task_comms/core.py:50-75`
- `CoreClient.login(self, username, secret)` — `/usr/lib/python3/dist-packages/task_comms/core.py:77-80`
- `CoreClient.logout(self)` — `/usr/lib/python3/dist-packages/task_comms/core.py:82-88`
- `CoreClient.has_role(self, needed)` — `/usr/lib/python3/dist-packages/task_comms/core.py:90-91`
- `CoreClient.assignment(self, role_name)` — `/usr/lib/python3/dist-packages/task_comms/core.py:93-101` — {device_id, alias, connected} assigned to a logical role (e.g. 'mesh.primary'), or None.

## `/usr/lib/python3/dist-packages/task_comms/events.py`
SHA-256: `0585a5ae2f8e1f56fd483c25e0e8040fda1674122886e2546f84cebb35e2dadd`

- `redact(value)` — `/usr/lib/python3/dist-packages/task_comms/events.py:15-22`
- `EventLog.__init__(self, path: Path, clock=time.time, max_bytes=2000000)` — `/usr/lib/python3/dist-packages/task_comms/events.py:26-29`
- `EventLog.log(self, event: str, **fields)` — `/usr/lib/python3/dist-packages/task_comms/events.py:31-38`

## `/usr/lib/python3/dist-packages/task_comms/feeds.py`
SHA-256: `3c8315f81fd62bfd810a9a688a51679b1984c98fac8393003b488a9fcc6c634a`

- `feed_path(producer: str, directory: Path=None) -> Path` — `/usr/lib/python3/dist-packages/task_comms/feeds.py:47-50`
- `FeedWriter.__init__(self, producer: str, directory: Path=None, clock=time.time)` — `/usr/lib/python3/dist-packages/task_comms/feeds.py:54-66`
- `FeedWriter._touch(self)` — `/usr/lib/python3/dist-packages/task_comms/feeds.py:68-70`
- `FeedWriter.upsert(self, e: Entity)` — `/usr/lib/python3/dist-packages/task_comms/feeds.py:72-80`
- `FeedWriter.remove(self, entity_id: str)` — `/usr/lib/python3/dist-packages/task_comms/feeds.py:82-84`
- `FeedWriter.clear(self)` — `/usr/lib/python3/dist-packages/task_comms/feeds.py:86-88`
- `FeedWriter.close(self)` — `/usr/lib/python3/dist-packages/task_comms/feeds.py:90-91`
- `read_feed(path: Path, clock=time.time)` — `/usr/lib/python3/dist-packages/task_comms/feeds.py:94-126` — (updated_ts or None, [dict]) — never raises for missing/corrupt files.
- `list_feeds(directory: Path=None)` — `/usr/lib/python3/dist-packages/task_comms/feeds.py:129-131`

## `/usr/lib/python3/dist-packages/task_comms/notifications.py`
SHA-256: `6403f8fe6abe0e8d95a3a154b66099e98b50f9497ec9b26214d056f7b577a210`

- `mesh_source(protocol)` — `/usr/lib/python3/dist-packages/task_comms/notifications.py:46-49`
- `NotificationStore.__init__(self, path: Path=None)` — `/usr/lib/python3/dist-packages/task_comms/notifications.py:91-102`
- `NotificationStore.close(self)` — `/usr/lib/python3/dist-packages/task_comms/notifications.py:104-105`
- `NotificationStore.record(self, n: Notification) -> bool` — `/usr/lib/python3/dist-packages/task_comms/notifications.py:107-119` — -> True if new (a consumer may announce it), False for a duplicate or a history-sync item.
- `NotificationStore.unread(self, source)` — `/usr/lib/python3/dist-packages/task_comms/notifications.py:121-135` — Per conversation: {conversation: {"count", "priority", "last_sender", "last_preview"}}.
- `NotificationStore.badge(self, source)` — `/usr/lib/python3/dist-packages/task_comms/notifications.py:137-140`
- `NotificationStore.badge_group(self, prefix='mesh.')` — `/usr/lib/python3/dist-packages/task_comms/notifications.py:142-150` — Combined badge over every source starting with prefix, plus the per-source breakdown. Read-only.
- `NotificationStore.mark_read(self, source, conversation)` — `/usr/lib/python3/dist-packages/task_comms/notifications.py:152-155`
- `NotificationStore.mark_all_read(self, source, confirm=False)` — `/usr/lib/python3/dist-packages/task_comms/notifications.py:157-162`
- `NotificationStore.count_all(self, source)` — `/usr/lib/python3/dist-packages/task_comms/notifications.py:164-166`
- `classify_priority(text, packet_priority, sender, conversation, rules=())` — `/usr/lib/python3/dist-packages/task_comms/notifications.py:169-178` — -> (priority, reason) from protocol metadata or user rules only.
- `from_meshtastic(packet, my_node_num, origin=LIVE, privacy=False, channel_names=None, node_names=None, rules=(), source='mesh')` — `/usr/lib/python3/dist-packages/task_comms/notifications.py:181-208` — Decoded Meshtastic packet dict (as the meshtastic Python API delivers it) -> Notification | None.
- `from_meshcore(payload, kind, origin=LIVE, privacy=False, contact_names=None, channel_names=None, rules=(), message_id=None, received_at=None)` — `/usr/lib/python3/dist-packages/task_comms/notifications.py:211-251` — meshcore_py CONTACT_MSG_RECV / CHANNEL_MSG_RECV payload -> Notification | None (0.3.1).
- `desktop_notification(n: Notification, privacy=False, locked=False, protocol_label=None, sound=True, show_sender=True)` — `/usr/lib/python3/dist-packages/task_comms/notifications.py:254-277` — Arguments for org.freedesktop.Notifications.Notify (Desktop Notifications Spec 1.2), no shell.

## `/usr/lib/python3/dist-packages/task_comms/ownership.py`
SHA-256: `02f06cc1a68201cd60705656f50ad06aa71a0bf857069899335c4bb120b91a60`

- `holders(device: str, proc_root: Path=Path('/proc'), self_pid: int=None)` — `/usr/lib/python3/dist-packages/task_comms/ownership.py:18-48` — [(pid, comm)] of visible processes with device open.
- `DeviceClaim.__init__(self, device_key: str, module: str, directory: Path=None)` — `/usr/lib/python3/dist-packages/task_comms/ownership.py:54-59`
- `DeviceClaim.acquire(self) -> bool` — `/usr/lib/python3/dist-packages/task_comms/ownership.py:61-74`
- `DeviceClaim.holder(self)` — `/usr/lib/python3/dist-packages/task_comms/ownership.py:76-80`
- `DeviceClaim.release(self)` — `/usr/lib/python3/dist-packages/task_comms/ownership.py:82-85`
- `DeviceClaim.__enter__(self)` — `/usr/lib/python3/dist-packages/task_comms/ownership.py:87-90`
- `DeviceClaim.__exit__(self, *a)` — `/usr/lib/python3/dist-packages/task_comms/ownership.py:92-93`

## `/usr/lib/python3/dist-packages/task_comms/paths.py`
SHA-256: `9a17fc7eae49564053799c3bafd368cbc6b7ee949104151d9fbf1711ee51ac0d`

- `_xdg(var, default)` — `/usr/lib/python3/dist-packages/task_comms/paths.py:9-11`
- `runtime_dir() -> Path` — `/usr/lib/python3/dist-packages/task_comms/paths.py:14-16`
- `status_dir() -> Path` — `/usr/lib/python3/dist-packages/task_comms/paths.py:19-20`
- `data_dir(module: str) -> Path` — `/usr/lib/python3/dist-packages/task_comms/paths.py:23-24`
- `config_dir(module: str) -> Path` — `/usr/lib/python3/dist-packages/task_comms/paths.py:27-28`
- `state_dir(module: str) -> Path` — `/usr/lib/python3/dist-packages/task_comms/paths.py:31-32`
- `feeds_dir() -> Path` — `/usr/lib/python3/dist-packages/task_comms/paths.py:35-36`
- `private_dir(path: Path) -> Path` — `/usr/lib/python3/dist-packages/task_comms/paths.py:39-42`

## `/usr/lib/python3/dist-packages/task_comms/status.py`
SHA-256: `a656d05bfd0b6cff5fba350b36d6d16229ff08e2c29da7d7b026b72a09ab0602`

- `StatusWriter.__init__(self, module: str, directory: Path=None, clock=time.time)` — `/usr/lib/python3/dist-packages/task_comms/status.py:27-33`
- `StatusWriter.write(self, state: str, *, device=None, summary='', counts=None, last_error=None, indicators=None)` — `/usr/lib/python3/dist-packages/task_comms/status.py:35-56`
- `StatusWriter.heartbeat(self)` — `/usr/lib/python3/dist-packages/task_comms/status.py:58-65`
- `StatusWriter.remove(self)` — `/usr/lib/python3/dist-packages/task_comms/status.py:67-71`
- `_pid_alive(pid) -> bool` — `/usr/lib/python3/dist-packages/task_comms/status.py:74-79`
- `read_status(path: Path, clock=time.time, pid_alive=_pid_alive)` — `/usr/lib/python3/dist-packages/task_comms/status.py:82-99` — Parsed card plus derived '_stale' / '_dead'; None if absent; {'_invalid': reason} if unreadable.
- `read_all(directory: Path=None, **kw) -> dict` — `/usr/lib/python3/dist-packages/task_comms/status.py:102-108`

## `/usr/lib/python3/dist-packages/task_comms/txpolicy.py`
SHA-256: `ed037073766d9a05e027caec3969e618dddf8e4e29992f43e843d963d873a821`

- `valid_amateur_callsign(text: str) -> bool` — `/usr/lib/python3/dist-packages/task_comms/txpolicy.py:56-60`
- `valid_gmrs_callsign(text: str) -> bool` — `/usr/lib/python3/dist-packages/task_comms/txpolicy.py:63-64`
- `is_gmrs_data_channel(mhz) -> bool` — `/usr/lib/python3/dist-packages/task_comms/txpolicy.py:67-72`
- `Decision.code(self)` — `/usr/lib/python3/dist-packages/task_comms/txpolicy.py:83-84`
- `TxPolicy.__init__(self, clock=time.monotonic)` — `/usr/lib/python3/dist-packages/task_comms/txpolicy.py:144-150`
- `TxPolicy._common(self, req: TxRequest, d: Decision)` — `/usr/lib/python3/dist-packages/task_comms/txpolicy.py:153-159`
- `TxPolicy._duplicate(self, req, d)` — `/usr/lib/python3/dist-packages/task_comms/txpolicy.py:161-166`
- `TxPolicy.evaluate_amateur(self, req: TxRequest, cfg: AmateurConfig, radio: AmateurRadio) -> Decision` — `/usr/lib/python3/dist-packages/task_comms/txpolicy.py:169-204`
- `TxPolicy.evaluate_gmrs(self, req: TxRequest, cfg: GmrsConfig, eq: GmrsEquipment) -> Decision` — `/usr/lib/python3/dist-packages/task_comms/txpolicy.py:207-261`
- `TxPolicy.record_sent(self, req: TxRequest, channel=None, request_id=None)` — `/usr/lib/python3/dist-packages/task_comms/txpolicy.py:264-271`
- `TxPolicy.frame_done(self, channel)` — `/usr/lib/python3/dist-packages/task_comms/txpolicy.py:273-274`
- `TxPolicy.voice_id_done(self)` — `/usr/lib/python3/dist-packages/task_comms/txpolicy.py:276-278`
- `retry_schedule(count: int=RETRY_DEFAULT)` — `/usr/lib/python3/dist-packages/task_comms/txpolicy.py:281-289` — User-chosen retries (default 3, max 5): seconds after the first send.

## `/usr/lib/task-aprs/task_aprs/__init__.py`
SHA-256: `402963eb63abb8cf540a8da28d81312d3fae8037f03ca89d7e6143505efcde44`


## `/usr/lib/task-aprs/task_aprs/agw.py`
SHA-256: `780c390b1d979bf69b89049b526591cddf6bd5f999b02250271c4e786b89fbb5`

- `pack(kind: str, port: int=0, data: bytes=b'', pid: int=0, call_from: str='', call_to: str='') -> bytes` — `/usr/lib/task-aprs/task_aprs/agw.py:29-30`
- `unpack_header(buf: bytes)` — `/usr/lib/task-aprs/task_aprs/agw.py:33-38`
- `AgwClient.__init__(self, host='127.0.0.1', port=8000, timeout=3.0, on_frame=None, on_close=None)` — `/usr/lib/task-aprs/task_aprs/agw.py:48-56`
- `AgwClient.connect(self)` — `/usr/lib/task-aprs/task_aprs/agw.py:59-66`
- `AgwClient.close(self)` — `/usr/lib/task-aprs/task_aprs/agw.py:68-75`
- `AgwClient.connected(self)` — `/usr/lib/task-aprs/task_aprs/agw.py:78-79`
- `AgwClient._send(self, data: bytes)` — `/usr/lib/task-aprs/task_aprs/agw.py:81-85`
- `AgwClient._recv_exact(self, n)` — `/usr/lib/task-aprs/task_aprs/agw.py:87-94`
- `AgwClient._read_loop(self)` — `/usr/lib/task-aprs/task_aprs/agw.py:96-116`
- `AgwClient._wait(self, kind, port=None, timeout=None)` — `/usr/lib/task-aprs/task_aprs/agw.py:118-124`
- `AgwClient.version_text(self)` — `/usr/lib/task-aprs/task_aprs/agw.py:127-132`
- `AgwClient.port_info(self)` — `/usr/lib/task-aprs/task_aprs/agw.py:134-137`
- `AgwClient.enable_raw_rx(self)` — `/usr/lib/task-aprs/task_aprs/agw.py:139-140`
- `AgwClient.send_raw(self, channel: int, frame: bytes)` — `/usr/lib/task-aprs/task_aprs/agw.py:142-146` — Hand one raw AX.25 frame to Direwolf's transmit queue for channel.
- `AgwClient.outstanding(self, channel: int) -> int` — `/usr/lib/task-aprs/task_aprs/agw.py:148-153`

## `/usr/lib/task-aprs/task_aprs/amateur.py`
SHA-256: `ac80701e9afee9e4296cc43c4ed16026ba17d73a3475f29fd4847a3e433a66ab`

- `parse_path(text: str)` — `/usr/lib/task-aprs/task_aprs/amateur.py:35-39`
- `Outgoing.done(self)` — `/usr/lib/task-aprs/task_aprs/amateur.py:60-61`
- `AmateurTx.__init__(self, policy, audit, transport_getter, config_getter, radio_getter, role_getter, clock=time.monotonic, on_change=None)` — `/usr/lib/task-aprs/task_aprs/amateur.py:65-73`
- `AmateurTx._msg_id(self)` — `/usr/lib/task-aprs/task_aprs/amateur.py:76-77`
- `AmateurTx._set(self, o: Outgoing, state, note='')` — `/usr/lib/task-aprs/task_aprs/amateur.py:79-82`
- `AmateurTx.queued(self)` — `/usr/lib/task-aprs/task_aprs/amateur.py:84-86` — True while any of our frames is still waiting in Direwolf's queue (QUEUED indicator).
- `AmateurTx._evaluate(self, kind, addressee='', text='', confirmed=(), transport_name=None)` — `/usr/lib/task-aprs/task_aprs/amateur.py:88-98`
- `AmateurTx._audit(self, action, d, kind, info: str, radio, extra=None)` — `/usr/lib/task-aprs/task_aprs/amateur.py:100-106`
- `AmateurTx.preview(self, kind, addressee='', text='', lat=None, lon=None, comment='', path='WIDE1-1,WIDE2-1')` — `/usr/lib/task-aprs/task_aprs/amateur.py:108-114` — Exact frame that Send would hand to Direwolf (no side effects).
- `AmateurTx._info(self, kind, addressee, text, lat, lon, comment, msg_id)` — `/usr/lib/task-aprs/task_aprs/amateur.py:116-123`
- `AmateurTx.send(self, kind, *, addressee='', text='', lat=None, lon=None, comment='', ack_id=None, retries=3, path='WIDE1-1,WIDE2-1', confirmed=())` — `/usr/lib/task-aprs/task_aprs/amateur.py:126-150` — One explicit user action. Returns (Outgoing|None, Decision).
- `AmateurTx.cancel(self, local_id)` — `/usr/lib/task-aprs/task_aprs/amateur.py:152-158`
- `AmateurTx._transmit(self, o: Outgoing, req, t)` — `/usr/lib/task-aprs/task_aprs/amateur.py:161-178`
- `AmateurTx.tick(self)` — `/usr/lib/task-aprs/task_aprs/amateur.py:180-218` — Poll queue progress and run user-chosen retries. Call about once per second.
- `AmateurTx._fail(self, o, why)` — `/usr/lib/task-aprs/task_aprs/amateur.py:220-224`
- `AmateurTx.on_packet(self, frame, packet)` — `/usr/lib/task-aprs/task_aprs/amateur.py:227-250` — Called for every decoded RF frame (not for APRS-IS third-party content).

## `/usr/lib/task-aprs/task_aprs/app.py`
SHA-256: `d2c2ad08d8cb3151f3edd304144df391ca1cbac64a167402c421b5b065054f88`

- `main(argv=None)` — `/usr/lib/task-aprs/task_aprs/app.py:12-44`

## `/usr/lib/task-aprs/task_aprs/config.py`
SHA-256: `c74ded2de140f3038493454dcb767748d3bb6ebb8dd928ae16d95ca459005c1c`

- `config_root() -> Path` — `/usr/lib/task-aprs/task_aprs/config.py:23-24`
- `_toml_value(v)` — `/usr/lib/task-aprs/task_aprs/config.py:27-33`
- `write_toml(path: Path, data: dict)` — `/usr/lib/task-aprs/task_aprs/config.py:36-49`
- `read_toml(path: Path) -> dict` — `/usr/lib/task-aprs/task_aprs/config.py:52-57`
- `_build(cls, data: dict)` — `/usr/lib/task-aprs/task_aprs/config.py:60-62`
- `load_amateur(root: Path=None) -> AmateurConfig` — `/usr/lib/task-aprs/task_aprs/config.py:65-69`
- `save_amateur(cfg: AmateurConfig, root: Path=None)` — `/usr/lib/task-aprs/task_aprs/config.py:72-73`
- `load_gmrs(root: Path=None) -> GmrsConfig` — `/usr/lib/task-aprs/task_aprs/config.py:76-80`
- `save_gmrs(cfg: GmrsConfig, root: Path=None)` — `/usr/lib/task-aprs/task_aprs/config.py:83-84`
- `RadioProfile.validate(self)` — `/usr/lib/task-aprs/task_aprs/config.py:109-118`
- `radios_dir(root: Path=None) -> Path` — `/usr/lib/task-aprs/task_aprs/config.py:121-122`
- `save_profile(p: RadioProfile, root: Path=None)` — `/usr/lib/task-aprs/task_aprs/config.py:125-127`
- `load_profiles(service: str, root: Path=None)` — `/usr/lib/task-aprs/task_aprs/config.py:130-143`

## `/usr/lib/task-aprs/task_aprs/dwconf.py`
SHA-256: `902c221dc91df4a197e5d147452a48343c31a36c767cd391e6db2f3a2b2289aa`

- `DirewolfConfig.effective_agw_port(self)` — `/usr/lib/task-aprs/task_aprs/dwconf.py:41-42`
- `DirewolfConfig.effective_kiss_ports(self)` — `/usr/lib/task-aprs/task_aprs/dwconf.py:45-46`
- `DirewolfConfig.channel(self, n) -> Channel` — `/usr/lib/task-aprs/task_aprs/dwconf.py:48-49`
- `DirewolfConfig.warnings(self, callsign: str='', channel: int=0)` — `/usr/lib/task-aprs/task_aprs/dwconf.py:51-66`
- `parse(text: str, path: str='') -> DirewolfConfig` — `/usr/lib/task-aprs/task_aprs/dwconf.py:69-107`
- `load(paths=CANDIDATES) -> DirewolfConfig` — `/usr/lib/task-aprs/task_aprs/dwconf.py:110-119`

## `/usr/lib/task-aprs/task_aprs/gmrs/__init__.py`
SHA-256: `4cbd616f6109ccaeaf7bca31594d1989cc3c4543c803ac47083ecdc339ba2ecc`


## `/usr/lib/task-aprs/task_aprs/gmrs/driver.py`
SHA-256: `e790da9bb233164cd11cc37a9b6119c6dfde060b7702b45b563a4223a2fc420c`

- `GmrsDriver.capabilities(self) -> DriverCapabilities` — `/usr/lib/task-aprs/task_aprs/gmrs/driver.py:44-44`
- `GmrsDriver.open(self)` — `/usr/lib/task-aprs/task_aprs/gmrs/driver.py:47-47`
- `GmrsDriver.close(self)` — `/usr/lib/task-aprs/task_aprs/gmrs/driver.py:50-50`
- `GmrsDriver.connected(self) -> bool` — `/usr/lib/task-aprs/task_aprs/gmrs/driver.py:54-54`
- `GmrsDriver.current_channel_mhz(self)` — `/usr/lib/task-aprs/task_aprs/gmrs/driver.py:57-57`
- `GmrsDriver.request_transmit(self, kind: str, *, recipient: str='', text: str='', lat=None, lon=None) -> float` — `/usr/lib/task-aprs/task_aprs/gmrs/driver.py:60-62` — Ask the radio to send its own data packet; returns the radio-reported burst duration (s).
- `GmrsDriver.set_receive_callback(self, cb)` — `/usr/lib/task-aprs/task_aprs/gmrs/driver.py:64-65`
- `register(cls)` — `/usr/lib/task-aprs/task_aprs/gmrs/driver.py:71-73`

## `/usr/lib/task-aprs/task_aprs/gmrs/service.py`
SHA-256: `a0b98fed04aa74863cf0f0abc41a0c1e38aee9f502dd3d6eb7a0875b8efc7131`

- `equipment_from(driver, profile) -> GmrsEquipment` — `/usr/lib/task-aprs/task_aprs/gmrs/service.py:13-22` — Policy facts: both the driver AND the operator's profile (from the FCC grant) must agree.
- `GmrsTx.__init__(self, policy, audit, driver_getter, config_getter, profile_getter, role_getter, clock=time.monotonic, feed=None, on_receive=None)` — `/usr/lib/task-aprs/task_aprs/gmrs/service.py:26-31`
- `GmrsTx.status(self)` — `/usr/lib/task-aprs/task_aprs/gmrs/service.py:33-42`
- `GmrsTx.send(self, kind, *, recipient='', text='', lat=None, lon=None, confirmed=(), is_auto_reply=False)` — `/usr/lib/task-aprs/task_aprs/gmrs/service.py:44-82`
- `GmrsTx.voice_id_done(self)` — `/usr/lib/task-aprs/task_aprs/gmrs/service.py:84-86`
- `GmrsTx.handle_receive(self, pkt)` — `/usr/lib/task-aprs/task_aprs/gmrs/service.py:88-94`

## `/usr/lib/task-aprs/task_aprs/gmrs/simulated.py`
SHA-256: `9b2812fd88eca9d347df6779d8581dffbe08d8ec8132fe3340b93b85abd7541f`

- `SimulatedGmrsDriver.__init__(self, channel_mhz=462.5625, burst_s=0.4, clock=time.time, fail=False)` — `/usr/lib/task-aprs/task_aprs/gmrs/simulated.py:15-19`
- `SimulatedGmrsDriver.capabilities(self)` — `/usr/lib/task-aprs/task_aprs/gmrs/simulated.py:21-25`
- `SimulatedGmrsDriver.open(self)` — `/usr/lib/task-aprs/task_aprs/gmrs/simulated.py:27-28`
- `SimulatedGmrsDriver.close(self)` — `/usr/lib/task-aprs/task_aprs/gmrs/simulated.py:30-31`
- `SimulatedGmrsDriver.connected(self)` — `/usr/lib/task-aprs/task_aprs/gmrs/simulated.py:34-35`
- `SimulatedGmrsDriver.current_channel_mhz(self)` — `/usr/lib/task-aprs/task_aprs/gmrs/simulated.py:37-38`
- `SimulatedGmrsDriver.request_transmit(self, kind, *, recipient='', text='', lat=None, lon=None)` — `/usr/lib/task-aprs/task_aprs/gmrs/simulated.py:40-47`
- `SimulatedGmrsDriver.inject(self, kind, sender, **kw)` — `/usr/lib/task-aprs/task_aprs/gmrs/simulated.py:49-53`

## `/usr/lib/task-aprs/task_aprs/history.py`
SHA-256: `249c2dc70ead194788dfff546be875488731a519847253a9d52052a0c360207a`

- `History.__init__(self, path: Path=None)` — `/usr/lib/task-aprs/task_aprs/history.py:16-24`
- `History.add(self, ts, service, direction, peer, text, msg_id='', state='', via='RF')` — `/usr/lib/task-aprs/task_aprs/history.py:26-30`
- `History.set_state(self, row, state)` — `/usr/lib/task-aprs/task_aprs/history.py:32-34`
- `History.list(self, service, limit=500)` — `/usr/lib/task-aprs/task_aprs/history.py:36-38`
- `History.close(self)` — `/usr/lib/task-aprs/task_aprs/history.py:40-41`

## `/usr/lib/task-aprs/task_aprs/kiss.py`
SHA-256: `741d72bdf9d951a91763ff2ae946290deba33c49df3deb6d861f7a7a6568e0f6`

- `KissClient.__init__(self, host='127.0.0.1', port=8001, timeout=3.0, on_frame=None, on_close=None)` — `/usr/lib/task-aprs/task_aprs/kiss.py:17-21`
- `KissClient.connect(self)` — `/usr/lib/task-aprs/task_aprs/kiss.py:23-27`
- `KissClient.connected(self)` — `/usr/lib/task-aprs/task_aprs/kiss.py:30-31`
- `KissClient.close(self)` — `/usr/lib/task-aprs/task_aprs/kiss.py:33-40`
- `KissClient.send_raw(self, channel: int, frame: bytes)` — `/usr/lib/task-aprs/task_aprs/kiss.py:42-46`
- `KissClient._read_loop(self)` — `/usr/lib/task-aprs/task_aprs/kiss.py:48-65`

## `/usr/lib/task-aprs/task_aprs/netutil.py`
SHA-256: `9b82053e72151e22f2c65822abfd2439b1ae88f0ec5a0fdb308494e9a15916fa`

- `ensure_loopback(host: str) -> str` — `/usr/lib/task-aprs/task_aprs/netutil.py:8-16`

## `/usr/lib/task-aprs/task_aprs/rx.py`
SHA-256: `976fc231f7332ba0f29ebc0fad9bb753174e9fb5ee33db49a53e2b83e54dc638`

- `parse_third_party(p: codec.AprsPacket, now=None)` — `/usr/lib/task-aprs/task_aprs/rx.py:27-42` — Inner packet of a '}' third-party packet, or None.
- `Receiver.__init__(self, feed=None, clock=time.time, on_packet=None, on_station=None, on_message=None)` — `/usr/lib/task-aprs/task_aprs/rx.py:46-52`
- `Receiver.handle(self, channel: int, raw: bytes, mycall: str='')` — `/usr/lib/task-aprs/task_aprs/rx.py:54-75`
- `Receiver._station(self, p, via, now)` — `/usr/lib/task-aprs/task_aprs/rx.py:77-89`

## `/usr/lib/task-aprs/task_aprs/service.py`
SHA-256: `676bde5ab52f9d5ab68d6f6f7c7a7d17a3f3fe4f7dc86f17bf0909f1c9c3db50`

- `AprsService.__init__(self, session_role=lambda: None, conf_root=None, state_root=None, dw_conf=None, status_dir=None, feed_dir=None, clock=time.monotonic, wall=time.time, gmrs_driver=None, agw_factory=AgwClient, kiss_factory=KissClient)` — `/usr/lib/task-aprs/task_aprs/service.py:25-54`
- `AprsService.profile(self)` — `/usr/lib/task-aprs/task_aprs/service.py:57-58`
- `AprsService.gmrs_profile(self)` — `/usr/lib/task-aprs/task_aprs/service.py:60-61`
- `AprsService.radio(self)` — `/usr/lib/task-aprs/task_aprs/service.py:63-68`
- `AprsService.connect(self)` — `/usr/lib/task-aprs/task_aprs/service.py:71-92`
- `AprsService.disconnect(self)` — `/usr/lib/task-aprs/task_aprs/service.py:94-97`
- `AprsService._on_close(self)` — `/usr/lib/task-aprs/task_aprs/service.py:99-103`
- `AprsService._on_frame(self, channel, raw)` — `/usr/lib/task-aprs/task_aprs/service.py:105-107`
- `AprsService._on_packet(self, frame, packet, via)` — `/usr/lib/task-aprs/task_aprs/service.py:109-112`
- `AprsService._changed(self, obj)` — `/usr/lib/task-aprs/task_aprs/service.py:114-116`
- `AprsService.tick(self)` — `/usr/lib/task-aprs/task_aprs/service.py:119-122`
- `AprsService.write_status(self)` — `/usr/lib/task-aprs/task_aprs/service.py:124-133`
- `AprsService.close(self)` — `/usr/lib/task-aprs/task_aprs/service.py:135-140`

## `/usr/lib/task-mesh/task_mesh/hub/locks.py`
SHA-256: `9593cea93335056415fbddcb414a1431f54653d9d0b27b220cece4fdb82fd820`

- `runtime_dir(env=None) -> Path` — `/usr/lib/task-mesh/task_mesh/hub/locks.py:19-32`
- `Busy.__init__(self, owner: str) -> None` — `/usr/lib/task-mesh/task_mesh/hub/locks.py:36-38`
- `FileLock.__init__(self, path: Path, role: str) -> None` — `/usr/lib/task-mesh/task_mesh/hub/locks.py:42-45`
- `FileLock.held(self) -> bool` — `/usr/lib/task-mesh/task_mesh/hub/locks.py:48-49`
- `FileLock.acquire(self) -> 'FileLock'` — `/usr/lib/task-mesh/task_mesh/hub/locks.py:51-64`
- `FileLock.release(self) -> None` — `/usr/lib/task-mesh/task_mesh/hub/locks.py:66-73`
- `FileLock.__enter__(self)` — `/usr/lib/task-mesh/task_mesh/hub/locks.py:75-76`
- `FileLock.__exit__(self, *exc)` — `/usr/lib/task-mesh/task_mesh/hub/locks.py:78-79`
- `read_owner(path: Path) -> str` — `/usr/lib/task-mesh/task_mesh/hub/locks.py:82-87`
- `is_locked(path: Path) -> bool` — `/usr/lib/task-mesh/task_mesh/hub/locks.py:90-103` — Non-destructive check (try-lock + immediate unlock).
- `device_lock_name(path: str) -> str` — `/usr/lib/task-mesh/task_mesh/hub/locks.py:106-109`
- `device_lock(path: str, role: str, env=None) -> FileLock` — `/usr/lib/task-mesh/task_mesh/hub/locks.py:112-113`
- `instance_lock(env=None) -> FileLock` — `/usr/lib/task-mesh/task_mesh/hub/locks.py:116-117`
- `service_running(env=None) -> bool` — `/usr/lib/task-mesh/task_mesh/hub/locks.py:120-121`

## `/usr/lib/task-mesh/task_mesh/hub/notifier.py`
SHA-256: `2864d2425cee7be738863139f4edb1a6d9fd83345693a5690503a46c933bbe1a`

- `NotifySettings.is_quiet(self, now=None) -> bool` — `/usr/lib/task-mesh/task_mesh/hub/notifier.py:37-49`
- `NotifySettings.from_dict(cls, d: dict) -> 'NotifySettings'` — `/usr/lib/task-mesh/task_mesh/hub/notifier.py:52-59`
- `NotifySettings.to_dict(self) -> dict` — `/usr/lib/task-mesh/task_mesh/hub/notifier.py:61-65`
- `session_bus_address(env=None) -> Optional[str]` — `/usr/lib/task-mesh/task_mesh/hub/notifier.py:74-84` — DBUS_SESSION_BUS_ADDRESS, else the systemd user bus socket ($XDG_RUNTIME_DIR/bus, dbus-user-session).
- `JeepneySender.__init__(self, on_action: Optional[Callable[[int, str], None]]=None, on_closed: Optional[Callable[[int], None]]=None, address: Optional[str]=None) -> None` — `/usr/lib/task-mesh/task_mesh/hub/notifier.py:92-98`
- `JeepneySender._open(self)` — `/usr/lib/task-mesh/task_mesh/hub/notifier.py:100-111`
- `JeepneySender._reset(self) -> None` — `/usr/lib/task-mesh/task_mesh/hub/notifier.py:113-119`
- `JeepneySender._start_listener(self, router) -> None` — `/usr/lib/task-mesh/task_mesh/hub/notifier.py:121-152`
- `JeepneySender._call(self, member: str, sig: Optional[str]=None, body: tuple=(), dest=NOTIFY_NAME, path=NOTIFY_PATH, iface=NOTIFY_NAME)` — `/usr/lib/task-mesh/task_mesh/hub/notifier.py:154-164`
- `JeepneySender.available(self) -> bool` — `/usr/lib/task-mesh/task_mesh/hub/notifier.py:166-172`
- `JeepneySender.server_information(self) -> Optional[tuple]` — `/usr/lib/task-mesh/task_mesh/hub/notifier.py:174-178`
- `JeepneySender.capabilities(self) -> list` — `/usr/lib/task-mesh/task_mesh/hub/notifier.py:180-184`
- `JeepneySender.__call__(self, args: dict, replaces_id: int=0) -> Optional[int]` — `/usr/lib/task-mesh/task_mesh/hub/notifier.py:186-207`
- `JeepneySender.close(self) -> None` — `/usr/lib/task-mesh/task_mesh/hub/notifier.py:209-211`
- `format_notification(m: HubMessage, settings: 'NotifySettings', locked: bool, burst: int=0) -> dict` — `/usr/lib/task-mesh/task_mesh/hub/notifier.py:214-236` — Notify arguments. Title is always TITLE. Unlocked: protocol always; sender if show_sender; preview only
- `NotificationManager.__init__(self, comms_store, sender: Callable[..., Optional[int]], settings: Optional[NotifySettings]=None, auth_state: Callable[[], str]=lambda: 'unknown', focus_state: Callable[[], bool]=lambda: False, clock=None) -> None` — `/usr/lib/task-mesh/task_mesh/hub/notifier.py:243-258`
- `NotificationManager.handle(self, m: HubMessage) -> Optional[dict]` — `/usr/lib/task-mesh/task_mesh/hub/notifier.py:260-315` — Record (dedupe) and maybe pop up. -> the Notify args that were sent, or None.
- `NotificationManager.closed(self, nid: int) -> None` — `/usr/lib/task-mesh/task_mesh/hub/notifier.py:317-320`
- `NotificationManager.mark_read(self, protocol: str, conversation: str) -> None` — `/usr/lib/task-mesh/task_mesh/hub/notifier.py:322-324`

## `/usr/lib/task-mesh/task_mesh/service.py`
SHA-256: `f9a23c2da27ae833f3b5bedd1eafd3d5f8e69cb55b14e024caac2856d2a55a93`

- `build_hub(paths, role: str, sender=None, factories=None, scan=None, lock_factory=None, comms_store=None, session_role=None)` — `/usr/lib/task-mesh/task_mesh/service.py:31-49`
- `launch_gui(row_id: int, env=None) -> bool` — `/usr/lib/task-mesh/task_mesh/service.py:55-68` — Start the Mesh window at one message: argv only, the argument is an internal integer row id (never content).
- `run(stop: threading.Event, paths=None, poll_s: float=3.0, hub_kwargs: Optional[dict]=None, env=None) -> int` — `/usr/lib/task-mesh/task_mesh/service.py:71-116`
- `main(argv: Optional[Sequence[str]]=None) -> int` — `/usr/lib/task-mesh/task_mesh/service.py:119-154`

## `/usr/share/task-launcher/task_launcher/registry/discovery.py`
SHA-256: `ae04e3aea4cc4b25a054f916e6a2390303eb49afb38c49a28b08825ab25e4b66`

- `default_dirs()` — `/usr/share/task-launcher/task_launcher/registry/discovery.py:37-42`
- `discover(dirs=None)` — `/usr/share/task-launcher/task_launcher/registry/discovery.py:45-82` — Return (manifests_by_id: dict, problems: list[Problem]).

## `/usr/share/task-launcher/task_launcher/registry/manifest.py`
SHA-256: `9a70b56f8752ac6d231f1d6099ae09063513f99d5e9da6c3d2a246fa253e41cc`

- `Manifest.candidates(self)` — `/usr/share/task-launcher/task_launcher/registry/manifest.py:74-75`
- `Manifest.label_for(self, argv)` — `/usr/share/task-launcher/task_launcher/registry/manifest.py:77-80`
- `Manifest.resolve_exec(self)` — `/usr/share/task-launcher/task_launcher/registry/manifest.py:82-101` — (argv or None, status, reason): the first exec candidate that passes the checks.
- `version_tuple(text)` — `/usr/share/task-launcher/task_launcher/registry/manifest.py:114-116`
- `_str(doc, key, limit, required=False, default='')` — `/usr/share/task-launcher/task_launcher/registry/manifest.py:119-131`
- `_strlist(value, key, limit=32, item_limit=128)` — `/usr/share/task-launcher/task_launcher/registry/manifest.py:134-139`
- `_argv(value, key)` — `/usr/share/task-launcher/task_launcher/registry/manifest.py:142-153`
- `_labels(value, candidates)` — `/usr/share/task-launcher/task_launcher/registry/manifest.py:156-167`
- `_actions(value)` — `/usr/share/task-launcher/task_launcher/registry/manifest.py:170-193`
- `_icon(value, manifest_dir: Path, warnings: list)` — `/usr/share/task-launcher/task_launcher/registry/manifest.py:196-227`
- `parse_text(text: str, path: Path=None, trust: str='user') -> Manifest` — `/usr/share/task-launcher/task_launcher/registry/manifest.py:230-235`
- `parse_doc(doc: dict, path: Path=None, trust: str='user') -> Manifest` — `/usr/share/task-launcher/task_launcher/registry/manifest.py:238-333`
- `load_file(path: Path, trust: str) -> Manifest` — `/usr/share/task-launcher/task_launcher/registry/manifest.py:336-355`

## `/usr/share/task-launcher/task_launcher/ui/main_window.py`
SHA-256: `81d6e862c5e240d2a81cb6f27f272cd2fff452c7ac3a06ac225a5dc6ba60c33d`

- `IdleFilter.__init__(self, window)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:51-54`
- `IdleFilter.attach(self, qwindow)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:56-62`
- `IdleFilter._forget(self, qwindow)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:64-65`
- `IdleFilter.detach_all(self)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:67-73`
- `IdleFilter.eventFilter(self, obj, ev)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:75-83`
- `LockOverlay.__init__(self, parent, sign_in, public)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:89-106`
- `MainWindow.__init__(self, link, settings=None, registry=None, procs=None, net_reader=None, desktop_scan=None, start_workers=True, motion_hint_fn=motion.system_animations_enabled, idle_clock=None, probe_fn=None)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:112-181`
- `MainWindow.start_workers(self)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:184-204`
- `MainWindow.stop_workers(self)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:206-213`
- `MainWindow._on_probes(self, result)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:215-226` — Probe results arrive on the GUI thread (queued signal from the worker).
- `MainWindow.refresh_probes(self)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:228-231` — Run the readiness probes again now (window Refresh buttons).
- `MainWindow.rescan(self)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:233-245` — Non-blocking rescan of installed desktop applications (and manifests).
- `MainWindow._reap(self, w)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:247-250`
- `MainWindow._on_scan(self, entries)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:252-257`
- `MainWindow._on_net(self, st)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:259-269`
- `MainWindow._on_motion_hint(self, enabled)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:271-273`
- `MainWindow._apply_motion(self)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:275-276`
- `MainWindow.apply_settings(self, rebuild=True)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:279-296`
- `MainWindow.open_settings(self)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:298-312`
- `MainWindow._settings_accepted(self, dlg)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:314-328`
- `MainWindow.rebuild(self)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:331-336`
- `MainWindow._refresh_children(self)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:338-340`
- `MainWindow.display_state(self, t)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:342-362` — (style key, state line) combining static status, runtime state and the role gate.
- `MainWindow.ready_state(self, t)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:364-369` — (text, level) secondary readiness line, or None. Display only (never changes status).
- `MainWindow.refresh_states(self)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:371-373`
- `MainWindow._on_outcome(self, out)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:375-394`
- `MainWindow.clear_error(self, key)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:396-400`
- `MainWindow.activate(self, t)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:402-447`
- `MainWindow.open_view(self, name)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:450-470` — Show a native view inside this window (one instance per view; reopening reuses it). Falls back to the
- `MainWindow.go_back(self)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:472-478`
- `MainWindow.go_home(self)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:480-483`
- `MainWindow.open_builtin(self, which)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:485-516`
- `MainWindow._mesh_unavailable_sheet(self, t)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:518-536` — Temporary, clearly labelled read-only status while task-mesh is not installed.
- `MainWindow.run_action(self, t, action)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:538-542` — Secondary manifest action (e.g. gpsmon in a terminal). argv only, process manager.
- `MainWindow._sheet(self, title, lines, buttons=())` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:544-547`
- `MainWindow.tile_menu(self, w, pos)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:550-579`
- `MainWindow.move_tile(self, key, delta)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:581-584`
- `MainWindow.remove_tile(self, key, confirm_parent=None)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:586-598`
- `MainWindow.show_tile(self, key)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:600-602`
- `MainWindow.add_desktop(self, desktop_id)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:604-608`
- `MainWindow.set_enabled(self, t, enabled)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:610-612`
- `MainWindow.rename_tile(self, t, parent)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:614-622`
- `MainWindow.change_icon(self, t, parent)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:624-631`
- `MainWindow.reset_layout(self)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:633-635`
- `MainWindow._link_changed(self, what)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:638-656`
- `MainWindow._on_tick(self)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:658-662`
- `MainWindow.note_input(self)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:664-665`
- `MainWindow._auth_clicked(self)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:667-674`
- `MainWindow.request_sign_in(self)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:676-685`
- `MainWindow._do_login(self, dlg, username, password)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:687-704`
- `MainWindow._lock_changed(self, locked)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:706-718`
- `MainWindow._shortcuts(self)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:721-729`
- `MainWindow._refresh_all(self)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:731-733`
- `MainWindow.toggle_fullscreen(self)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:735-739`
- `MainWindow.resizeEvent(self, e)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:741-744`
- `MainWindow.showEvent(self, e)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:746-748`
- `MainWindow.closeEvent(self, e)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:750-752`
- `MainWindow.shutdown(self)` — `/usr/share/task-launcher/task_launcher/ui/main_window.py:754-777` — Graceful close: stop workers and timers, revoke the session once, keep launched apps running.

## `/usr/share/task-launcher/task_launcher/services/direwolf.py`
SHA-256: `68446da84c71c38e960131e317ad9565d82b809197f20aeba6bf339004eb2332`

- `DirewolfConfig.effective_kiss_ports(self)` — `/usr/share/task-launcher/task_launcher/services/direwolf.py:38-41`
- `DirewolfConfig.effective_agw_port(self)` — `/usr/share/task-launcher/task_launcher/services/direwolf.py:44-45`
- `DirewolfConfig.transmit_capable(self)` — `/usr/share/task-launcher/task_launcher/services/direwolf.py:48-49`
- `parse_config(text: str, path: str='') -> DirewolfConfig` — `/usr/share/task-launcher/task_launcher/services/direwolf.py:52-90`
- `DirewolfStatus.running(self)` — `/usr/share/task-launcher/task_launcher/services/direwolf.py:103-104`
- `DirewolfStatus.open_kiss_port(self)` — `/usr/share/task-launcher/task_launcher/services/direwolf.py:106-110`
- `DirewolfStatus.summary(self)` — `/usr/share/task-launcher/task_launcher/services/direwolf.py:112-121`
- `_config_paths(procs, units, home: Path)` — `/usr/share/task-launcher/task_launcher/services/direwolf.py:124-143`
- `collect(home: Path=None, procs_fn=None, units_fn=None, binary_fn=None, port_fn=probe.tcp_reachable)` — `/usr/share/task-launcher/task_launcher/services/direwolf.py:146-176`
