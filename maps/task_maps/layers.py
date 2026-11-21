# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Map files available for display: downloaded (``maps/<source>.mbtiles``) and imported
(``maps/imported/*.mbtiles``, copied or symlinked by the offline import)."""

import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from task_maps import mbtiles


@dataclass
class Layer:
    path: str
    name: str
    kind: str              # downloaded | imported
    attribution: str = ""
    minzoom: int = None
    maxzoom: int = None
    tiles: int = 0
    problem: str = ""
    bounds: tuple = None


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]{0,200}>", "", s or "").replace("&copy;", "©").replace("&amp;", "&").strip()


def describe(path, kind) -> Layer:
    ok, msg, md = mbtiles.check(path)
    lay = Layer(str(path), md.get("name") or Path(path).stem, kind, _strip_html(md.get("attribution", ""))[:300])
    if not ok:
        lay.problem = msg
        return lay
    try:
        r = mbtiles.Reader(path)
        lay.minzoom, lay.maxzoom = r.zoom_range()
        lay.tiles = r.count()
        r.close()
    except Exception as exc:   # noqa: BLE001
        lay.problem = str(exc)
    b = md.get("bounds", "")
    try:
        parts = [float(v) for v in b.split(",")]
        if len(parts) == 4:
            lay.bounds = tuple(parts)
    except ValueError:
        pass
    return lay


def scan(data_dir):
    maps = Path(data_dir) / "maps"
    out = []
    for kind, d in (("downloaded", maps), ("imported", maps / "imported")):
        try:
            names = sorted(n for n in os.listdir(d) if n.endswith(".mbtiles"))
        except OSError:
            continue
        for n in names:
            out.append(describe(d / n, kind))
    return out


def safe_name(name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name).stem).strip("-.")[:60] or "map"
    return base + ".mbtiles"


def import_mbtiles(src, data_dir, link=False, progress=None):
    """Validate and copy (or symlink) an MBTiles file into ``maps/imported``. Works offline.
    Returns the new path; raises ValueError with the reason if the file is not usable."""
    src = Path(src)
    ok, msg, md = mbtiles.check(src, quick=False)
    if not ok:
        raise ValueError(f"{src.name}: {msg}")
    dest_dir = Path(data_dir) / "maps" / "imported"
    dest_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    base = safe_name(src.name)[:-len(".mbtiles")]
    dest = dest_dir / f"{base}.mbtiles"
    i = 2
    while dest.exists() or dest.is_symlink():
        dest = dest_dir / f"{base}-{i}.mbtiles"
        i += 1
    if link:
        os.symlink(src.resolve(), dest)
        return dest
    size = src.stat().st_size
    free = shutil.disk_usage(dest_dir).free
    if size + 64 * 1024 * 1024 > free:
        raise OSError(f"not enough free space to copy {size // (1024 * 1024)} MiB (free {free // (1024 * 1024)} MiB)")
    tmp = dest.with_suffix(".part")
    try:
        # SQLite online backup: a consistent copy even if the source uses WAL with a -wal file.
        s_con = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=10)
        d_con = sqlite3.connect(str(tmp))
        try:
            s_con.backup(d_con, pages=1024,
                         progress=(lambda st, remaining, total: progress(total - remaining, total)) if progress else None)
            d_con.execute("PRAGMA journal_mode=DELETE")
        finally:
            d_con.close()
            s_con.close()
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return dest
