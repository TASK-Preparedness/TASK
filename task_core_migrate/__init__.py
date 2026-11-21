# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-core-migrate: copy-only migration rain-core -> task-core (Phase 4C stages M1-M3).

    task-core-migrate --dry-run      # report the plan, change nothing
    task-core-migrate                # migrate (resumes an interrupted run)
    task-core-migrate --rollback     # return to rain-core; legacy data was never modified

Never moves or deletes legacy data. /etc/rain and /var/lib/rain are only read,
plus (at the very end) a MIGRATED-TO-TASK note and chmod 0550 on /var/lib/rain,
both reversed by --rollback. Account/group rename (M4) and legacy cleanup (M5)
are NOT done here; they need separate approvals.

Every step is journaled to /var/lib/task/.migrate-journal.json (atomic replace +
fsync) so a power cut at any point leaves either the legacy system fully intact
(it is never written before the final steps) or a resumable state. The migration
holds the same flock (/var/lib/task/.lock) task-core takes at startup.

The tool is a separate package (not task_core) because it must run as root
while task-core itself must never run as root.

--root PREFIX runs against a sandbox tree (tests); --systemctl is only accepted
together with a non-/ --root. No shell, absolute argv only.
"""

import argparse
import datetime
import fcntl
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path

SYSTEMCTL = "/usr/bin/systemctl"
LEGACY_UNIT = "rain-core.service"
NEW_UNIT = "task-core.service"
PATH_REWRITES = (("/run/rain/", "/run/task/"), ("/var/lib/rain", "/var/lib/task"),
                 ("/usr/lib/rain", "/usr/lib/task-core"), ("/etc/rain", "/etc/task"))
TREES = (("etc/rain", "etc/task"), ("var/lib/rain", "var/lib/task"))
SKIP_NAMES = {".lock", ".migrate-journal.json"}
STEPS = ("preflight", "stop-legacy", "backup", "copy", "verify", "rewrite", "promote",
         "disable-legacy", "legacy-readonly", "marker")


class MigrateError(Exception):
    pass


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def _fsync_dir(path: Path):
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def rewrite_text(text: str) -> str:
    for old, new in PATH_REWRITES:
        text = text.replace(old, new)
    return text


def manifest(tree: Path) -> dict:
    """relative path -> {type, mode, uid, gid, sha256|target} for every entry below tree."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(tree):
        dirnames.sort()
        for name in sorted(dirnames) + sorted(filenames):
            p = Path(dirpath) / name
            rel = str(p.relative_to(tree))
            if rel in SKIP_NAMES or rel.startswith(".staging"):
                continue
            st = p.lstat()
            entry = {"mode": stat.S_IMODE(st.st_mode), "uid": st.st_uid, "gid": st.st_gid}
            if stat.S_ISLNK(st.st_mode):
                entry.update(type="link", target=os.readlink(p))
            elif stat.S_ISDIR(st.st_mode):
                entry["type"] = "dir"
            elif stat.S_ISREG(st.st_mode):
                entry.update(type="file", sha256=sha256(p))
            else:
                entry["type"] = "other"
            out[rel] = entry
    return out


class Systemctl:
    def __init__(self, path=SYSTEMCTL):
        self.path = path

    def run(self, *args) -> int:
        return subprocess.run([self.path, *args], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, check=False).returncode

    def is_active(self, unit) -> bool:
        return self.run("is-active", "--quiet", unit) == 0

    def is_enabled(self, unit) -> bool:
        return self.run("is-enabled", "--quiet", unit) == 0


class Migrator:
    def __init__(self, root="/", systemctl=None, out=None, euid=None):
        self.root = Path(root)
        self.sc = systemctl or Systemctl()
        self.out = out or sys.stdout
        self.euid = os.geteuid() if euid is None else euid
        self.state_new = self.p("var/lib/task")
        self.journal_path = self.state_new / ".migrate-journal.json"
        self._lock_fd = None
        self.journal = {}

    def p(self, rel) -> Path:
        return self.root / rel

    def say(self, msg):
        print(msg, file=self.out, flush=True)

    # --- journal / lock -------------------------------------------------
    def load_journal(self):
        if self.journal_path.is_file():
            self.journal = json.loads(self.journal_path.read_text(encoding="utf-8"))
        return self.journal

    def save_journal(self):
        tmp = self.journal_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.journal, f, indent=1, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.journal_path)
        _fsync_dir(self.journal_path.parent)

    def done(self, step):
        return step in self.journal.get("done", [])

    def mark(self, step, **data):
        self.journal.setdefault("done", []).append(step)
        self.journal.update(data)
        self.save_journal()
        self.say(f"  [ok] {step}")

    def lock(self):
        self.state_new.mkdir(parents=True, exist_ok=True)
        os.chmod(self.state_new, 0o750)
        fd = os.open(str(self.state_new / ".lock"), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise MigrateError("/var/lib/task is locked: task-core or another migration is running") from None
        self._lock_fd = fd

    def unlock(self):
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None

    # --- plan -----------------------------------------------------------
    def preflight(self):
        problems = []
        if not self.p("etc/rain/core.toml").is_file():
            problems.append("legacy /etc/rain/core.toml not found (nothing to migrate)")
        if not self.p("var/lib/rain").is_dir():
            problems.append("legacy /var/lib/rain not found")
        if self.p("etc/task/MIGRATED").exists():
            problems.append("already migrated (/etc/task/MIGRATED exists); use --rollback to undo")
        if self.sc.is_active(NEW_UNIT):
            problems.append("task-core.service is active; stop it first")
        for _old, new in TREES:
            target = self.p(new)
            if target.is_dir():
                extra = [c.name for c in target.iterdir()
                         if c.name not in SKIP_NAMES and not c.name.startswith(".staging")
                         and not c.name.endswith(".tmp")]
                if extra and not self.journal.get("started"):
                    problems.append(f"/{new} already has content ({', '.join(sorted(extra)[:5])}); refusing to overwrite")
        return problems

    def dry_run(self) -> int:
        self.say("task-core-migrate --dry-run (no changes)")
        for line in self.preflight() or ["preflight: OK"]:
            self.say("  " + line)
        legacy_active = self.sc.is_active(LEGACY_UNIT)
        self.say(f"  rain-core.service active: {'yes (would be stopped)' if legacy_active else 'no'}")
        for old, new in TREES:
            src = self.p(old)
            n = len(manifest(src)) if src.is_dir() else 0
            self.say(f"  would copy /{old} -> /{new} ({n} entries; legacy left untouched)")
        core = self.p("etc/rain/core.toml")
        if core.is_file():
            text = core.read_text(encoding="utf-8")
            for a, b in zip(text.splitlines(), rewrite_text(text).splitlines()):
                if a != b:
                    self.say(f"  core.toml: {a.strip()}  ->  {b.strip()}")
        self.say("  would disable rain-core.service, write /var/lib/rain/MIGRATED-TO-TASK, chmod /var/lib/rain 0550,"
                 " write /etc/task/MIGRATED")
        self.say("  would NOT rename accounts/groups (M4) or remove legacy files (M5)")
        return 1 if self.preflight() else 0

    # --- migrate ----------------------------------------------------------
    def migrate(self) -> int:
        self.lock()
        try:
            self.load_journal()
            if self.journal.get("rolled_back"):
                self.journal = {}
            if self.journal.get("finished"):
                self.say("already migrated (finished " + self.journal["finished"] + "); use --rollback to undo")
                return 1
            resumed = bool(self.journal.get("started"))
            self.say("task-core-migrate: " + ("resuming interrupted migration" if resumed else "starting"))
            if not self.done("preflight"):
                problems = self.preflight()
                if problems:
                    for line in problems:
                        self.say("  refused: " + line)
                    return 1
                self.journal = {"started": _now(), "version": 1}
                self.mark("preflight", legacy_was_active=self.sc.is_active(LEGACY_UNIT),
                          legacy_was_enabled=self.sc.is_enabled(LEGACY_UNIT),
                          legacy_mode=stat.S_IMODE(self.p("var/lib/rain").stat().st_mode))
            if not self.done("stop-legacy"):
                if self.sc.is_active(LEGACY_UNIT):
                    self.sc.run("stop", LEGACY_UNIT)
                if self.sc.is_active(LEGACY_UNIT):
                    raise MigrateError("rain-core.service did not stop")
                self.mark("stop-legacy")
            if not self.done("backup"):
                self.mark("backup", **self.backup())
            if not self.done("copy"):
                self.copy()
                self.mark("copy")
            if not self.done("verify"):
                self.verify()
                self.mark("verify")
            if not self.done("rewrite"):
                self.rewrite()
                self.mark("rewrite")
            if not self.done("promote"):
                self.promote()
                self.mark("promote")
            if not self.done("disable-legacy"):
                if self.journal.get("legacy_was_enabled"):
                    self.sc.run("disable", LEGACY_UNIT)
                self.mark("disable-legacy")
            if not self.done("legacy-readonly"):
                note = self.p("var/lib/rain/MIGRATED-TO-TASK")
                if not note.exists():
                    note.write_text(f"Data copied to /var/lib/task by task-core-migrate at {self.journal['started']}.\n"
                                    "Undo with: task-core-migrate --rollback\n", encoding="utf-8")
                os.chmod(self.p("var/lib/rain"), 0o550)
                self.mark("legacy-readonly")
            if not self.done("marker"):
                marker = self.p("etc/task/MIGRATED")
                marker.write_text(f"migrated {self.journal['started']}\n", encoding="utf-8")
                _fsync_dir(marker.parent)
                self.mark("marker", finished=_now())
            self.say("migration complete. Legacy data is unchanged; rain-core can be restored with --rollback.")
            self.say("Next (manual, not run by this tool): systemctl start task-core.service")
            return 0
        finally:
            self.unlock()

    def backup(self) -> dict:
        dest = self.p("var/backups")
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / f"task-core-migrate-{self.journal['started']}.tar.gz"
        tmp = path.with_suffix(".partial")
        with tarfile.open(tmp, "w:gz") as tar:
            for old, _new in TREES:
                tar.add(str(self.p(old)), arcname=old)
        with open(tmp, "rb") as f:
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        legacy = {old: manifest(self.p(old)) for old, _new in TREES}
        return {"backup": str(Path("/") / path.relative_to(self.root)), "backup_sha256": sha256(path),
                "legacy_manifest": legacy}

    def _staging(self, new) -> Path:
        return self.p(new) / ".staging"

    def copy(self):
        for old, new in TREES:
            src, stage = self.p(old), self._staging(new)
            if stage.exists():
                shutil.rmtree(stage)  # partial copy from an interrupted run: start this tree again
            self.p(new).mkdir(parents=True, exist_ok=True)
            st = src.stat()
            os.chmod(self.p(new), stat.S_IMODE(st.st_mode))
            self._chown(self.p(new), st.st_uid, st.st_gid)
            stage.mkdir(mode=0o700)
            for rel, entry in self.journal["legacy_manifest"][old].items():
                self._copy_entry(src / rel, stage / rel, entry)
            _fsync_dir(stage)

    def _chown(self, path, uid, gid):
        if self.euid == 0:
            os.chown(path, uid, gid, follow_symlinks=False)

    def _copy_entry(self, src: Path, dst: Path, entry: dict):
        if entry["type"] == "dir":
            dst.mkdir(exist_ok=True)
        elif entry["type"] == "link":
            os.symlink(entry["target"], dst)
        elif entry["type"] == "file":
            self._copy_file(src, dst)
        else:
            return
        if entry["type"] != "link":
            os.chmod(dst, entry["mode"])
        self._chown(dst, entry["uid"], entry["gid"])

    def _copy_file(self, src: Path, dst: Path):
        with open(src, "rb") as fi, open(dst, "wb") as fo:
            shutil.copyfileobj(fi, fo)
            fo.flush()
            os.fsync(fo.fileno())

    def verify(self):
        for old, new in TREES:
            want = self.journal["legacy_manifest"][old]
            now_legacy = manifest(self.p(old))
            if now_legacy != want:
                raise MigrateError(f"/{old} changed during migration; aborting (nothing promoted)")
            got = manifest(self._staging(new))
            if self.euid != 0:  # unprivileged sandbox: ownership cannot be reproduced
                strip = lambda m: {k: {x: y for x, y in v.items() if x not in ("uid", "gid")} for k, v in m.items()}
                want, got = strip(want), strip(got)
            if got != want:
                diff = sorted(k for k in set(want) | set(got) if want.get(k) != got.get(k))
                raise MigrateError(f"copy of /{old} does not verify: {', '.join(diff[:5])}")
            for rel, entry in want.items():  # semantic check of structured files
                if entry["type"] != "file":
                    continue
                a, b = self.p(old) / rel, self._staging(new) / rel
                if rel.endswith(".json"):
                    if json.loads(a.read_bytes()) != json.loads(b.read_bytes()):
                        raise MigrateError(f"{rel}: JSON content differs")
                elif rel.endswith(".toml"):
                    if tomllib.loads(a.read_text("utf-8")) != tomllib.loads(b.read_text("utf-8")):
                        raise MigrateError(f"{rel}: TOML content differs")

    def rewrite(self):
        core = self._staging("etc/task") / "core.toml"
        old_doc = tomllib.loads(core.read_text("utf-8"))
        text = rewrite_text(core.read_text("utf-8"))
        new_doc = tomllib.loads(text)
        expect = {k: (rewrite_text(v) if isinstance(v, str) else v) for k, v in old_doc.items()}
        if new_doc != expect:
            raise MigrateError("core.toml rewrite is not a pure path rewrite")
        mode, st = stat.S_IMODE(core.stat().st_mode), core.stat()
        tmp = core.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        self._chown(tmp, st.st_uid, st.st_gid)
        os.replace(tmp, core)

    def promote(self):
        for _old, new in TREES:
            stage = self._staging(new)
            if not stage.exists():
                continue  # already promoted before an interruption
            for child in sorted(stage.iterdir()):
                os.replace(child, self.p(new) / child.name)
            _fsync_dir(self.p(new))
            stage.rmdir()

    # --- rollback -----------------------------------------------------------
    def rollback(self) -> int:
        self.lock()
        try:
            self.load_journal()
            if not self.journal.get("started") or self.journal.get("rolled_back"):
                self.say("nothing to roll back (no migration journal)")
                return 1
            self.say("task-core-migrate --rollback")
            if self.sc.is_active(NEW_UNIT):
                self.sc.run("stop", NEW_UNIT)
            if self.sc.is_active(NEW_UNIT):
                raise MigrateError("task-core.service did not stop")
            self.sc.run("disable", NEW_UNIT)
            marker = self.p("etc/task/MIGRATED")
            if marker.exists():
                marker.unlink()
            legacy = self.p("var/lib/rain")
            if "legacy_mode" in self.journal:
                os.chmod(legacy, self.journal["legacy_mode"])
            note = legacy / "MIGRATED-TO-TASK"
            if note.exists():
                note.unlink()
            want = self.journal.get("legacy_manifest", {})
            for old, _new in TREES:
                if old in want and manifest(self.p(old)) != want[old]:
                    raise MigrateError(f"/{old} differs from its pre-migration manifest; restore from "
                                       f"{self.journal.get('backup')} manually")
            stamp = _now()
            for _old, new in TREES:  # keep the copies (may hold newer task-core state); never delete
                target = self.p(new)
                if target.exists():
                    kept = target.parent / f"{target.name}.rolled-back-{stamp}"
                    for child in list(target.iterdir()):
                        if child.name in SKIP_NAMES:
                            continue
                        kept.mkdir(exist_ok=True, mode=0o700)
                        os.replace(child, kept / child.name)
            if self.journal.get("legacy_was_enabled"):
                self.sc.run("enable", LEGACY_UNIT)
            if self.journal.get("legacy_was_active"):
                self.sc.run("start", LEGACY_UNIT)
            self.journal = {"rolled_back": stamp}
            self.save_journal()
            self.say("rollback complete: rain-core restored; task-core copies kept as *.rolled-back-" + stamp)
            return 0
        finally:
            self.unlock()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="task-core-migrate", description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--rollback", action="store_true")
    ap.add_argument("--root", default="/", help=argparse.SUPPRESS)
    ap.add_argument("--systemctl", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.systemctl and os.path.realpath(args.root) == "/":
        ap.error("--systemctl is only allowed with a sandbox --root")
    if not os.path.isabs(args.root) or (args.systemctl and not os.path.isabs(args.systemctl)):
        ap.error("paths must be absolute")
    if os.path.realpath(args.root) == "/" and os.geteuid() != 0 and not args.dry_run:
        print("task-core-migrate must be run as root (sudo) on a real system", file=sys.stderr)
        return 2
    m = Migrator(args.root, Systemctl(args.systemctl or SYSTEMCTL))
    try:
        if args.dry_run:
            return m.dry_run()
        return m.rollback() if args.rollback else m.migrate()
    except MigrateError as exc:
        print(f"task-core-migrate: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
