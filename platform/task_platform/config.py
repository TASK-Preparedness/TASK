# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Per-user TOML configuration, same file format on Linux and Windows.

Read with the standard library (tomllib). Writes support the subset T.A.S.K. settings use (tables of
str/int/float/bool and lists of those) and are atomic (temporary file + os.replace), so a crash or power
loss never leaves a half-written file. Existing module configs on the Pi are never rewritten by this
module unless a module explicitly calls save().
"""
from __future__ import annotations

import math
import os
import tempfile
import tomllib
from pathlib import Path

from . import paths


def config_file(app: str, name: str = "config.toml", **kw):
    return paths.config_dir(app, **kw) / name   # PureWindowsPath when computed for Windows off-target


def load(path: os.PathLike, default: dict | None = None) -> dict:
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return dict(default or {})


def _value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError("non-finite float")
        return repr(v)
    if isinstance(v, str):
        return '"' + "".join(c if c not in '"\\\n\r\t' and ord(c) >= 0x20 else
                             {'"': '\\"', "\\": "\\\\", "\n": "\\n", "\r": "\\r", "\t": "\\t"}.get(c, f"\\u{ord(c):04x}")
                             for c in v) + '"'
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    raise TypeError(f"unsupported value type {type(v).__name__}")


def _key(k: str) -> str:
    if k and all(c.isalnum() or c in "-_" for c in k):
        return k
    return _value(k)


def dumps(data: dict) -> str:
    top = [f"{_key(k)} = {_value(v)}" for k, v in data.items() if not isinstance(v, dict)]
    out = top[:]
    for k, v in data.items():
        if isinstance(v, dict):
            if any(isinstance(x, dict) for x in v.values()):
                raise TypeError("nested tables deeper than one level are not supported")
            out += ["", f"[{_key(k)}]"] + [f"{_key(a)} = {_value(b)}" for a, b in v.items()]
    return "\n".join(out).lstrip("\n") + "\n"


def save(path: os.PathLike, data: dict) -> Path:
    path = Path(path)
    text = dumps(data)
    tomllib.loads(text)  # never write something we could not read back
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path
