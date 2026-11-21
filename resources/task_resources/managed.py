# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Optional managed storage: used only when the user explicitly asks to copy a file into it.

Default root ~/.local/share/task-resources/downloads/<category>/ (4E audit: per-user only), created on first
explicit use. Paths under settings.protected_roots (default /library) are refused. If the root is not
writable the fallback ~/.local/share/task-resources/managed/<category>/ is used and the caller is told so."""

import os
import shutil
from pathlib import Path

from task_resources import paths

CHUNK = 1 << 20


class ManagedError(Exception):
    pass


def _safe_part(name):
    name = "".join(c if (c.isalnum() or c in " ._-") else "_" for c in str(name)).strip(" .")
    return name[:80] or "Uncategorised"


def is_protected(path, settings):
    real = os.path.realpath(os.path.expanduser(str(path)))
    for root in getattr(settings, "protected_roots", ["/library"]):
        r = os.path.realpath(root).rstrip("/")
        if real == r or real.startswith(r + "/"):
            return True
    return False


def resolve_root(settings):
    """-> (root Path, note). Does not create anything."""
    want = Path(os.path.expanduser(settings.managed_root))
    if is_protected(want, settings):
        fb = paths.fallback_managed_root()
        return fb, f"{want} is a protected location (never written); using {fb} instead"
    probe = want
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if probe.is_dir() and os.access(probe, os.W_OK | os.X_OK):
        return want, ""
    fb = paths.fallback_managed_root()
    return fb, f"{want} is not writable by this user; using {fb} instead"


def copy_in(src, settings, category, job=None):
    """Copy src into managed storage (.part + fsync + atomic rename, never overwrites).
    -> (dest Path, note)."""
    src = Path(src)
    size = src.stat().st_size
    root, note = resolve_root(settings)
    dest_dir = root / _safe_part(category or "Uncategorised")
    dest_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(dest_dir).free
    reserve = int(settings.free_space_reserve_mb) * 1024 * 1024
    if free - size < reserve:
        raise ManagedError(f"not enough free space in {dest_dir}: need {size} bytes + {reserve} reserve, "
                           f"{free} free")
    dest = dest_dir / src.name
    n = 1
    while dest.exists():
        dest = dest_dir / f"{src.stem} ({n}){src.suffix}"
        n += 1
    part = dest.with_name("." + dest.name + ".part")
    done = 0
    try:
        with open(src, "rb") as fi, open(part, "xb") as fo:
            for chunk in iter(lambda: fi.read(CHUNK), b""):
                fo.write(chunk)
                done += len(chunk)
                if job:
                    job.progress(done=done, total=size, message=f"copying {src.name}")
            fo.flush()
            os.fsync(fo.fileno())
        if os.path.getsize(part) != size:
            raise ManagedError("copy is incomplete")
        os.chmod(part, 0o644)
        os.link(part, dest)          # atomic, fails instead of overwriting
        os.unlink(part)
    except BaseException:
        if part.exists():
            part.unlink()
        raise
    return dest, note


def managed_roots(settings):
    return [Path(os.path.expanduser(settings.managed_root)), paths.fallback_managed_root()]


def is_managed_path(path, settings):
    real = os.path.realpath(path)
    for root in managed_roots(settings):
        r = os.path.realpath(root)
        if real.startswith(r.rstrip("/") + "/"):
            return True
    return False


def usage(settings, index):
    """Storage overview: where managed files go, free space there, bytes used by managed resources."""
    root, note = resolve_root(settings)
    probe = root
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    du = shutil.disk_usage(probe)
    with index.lock:
        used = index.db.execute("SELECT COALESCE(SUM(size),0), COUNT(*) FROM resource "
                                "WHERE managed=1 AND missing=0").fetchone()
    return {"root": str(root), "note": note, "free": du.free, "total": du.total,
            "managed_bytes": used[0], "managed_count": used[1]}


def remove_managed(index, settings, rid):
    """Delete a T.A.S.K.-managed file AND its index row. External resources are refused (use Forget)."""
    r = index.get(rid)
    if r is None:
        raise ManagedError("unknown resource")
    if not r["managed"] or not is_managed_path(r["path"], settings):
        raise ManagedError("this file is not managed by T.A.S.K.; it can only be removed from the list "
                           "(Forget), the file itself is protected")
    p = Path(r["path"])
    if p.is_symlink():
        raise ManagedError("refusing to delete a symbolic link")
    if p.exists():
        p.unlink()
    index.remove(rid)
    return str(p)
