# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Import meshcore_py on Debian 13.

* Debian's python3-pycryptodome ships only the 'Cryptodome' namespace; meshcore imports 'Crypto'. If 'Crypto' is
  not importable, alias exactly the three modules meshcore uses (Crypto.Cipher.AES, Crypto.Hash.HMAC,
  Crypto.Hash.SHA256) to their Cryptodome equivalents in sys.modules. No files are installed.
* The 'meshcore' logger logs payloads and frames at DEBUG: pin it to WARNING, never propagate content.
"""

from __future__ import annotations

import importlib
import logging
import sys
import types

_ALIASES = ("Cipher", "Cipher.AES", "Hash", "Hash.HMAC", "Hash.SHA256")


def ensure_crypto() -> str:
    try:
        importlib.import_module("Crypto.Cipher.AES")
        importlib.import_module("Crypto.Hash.HMAC")
        importlib.import_module("Crypto.Hash.SHA256")
        return "Crypto"
    except ImportError:
        pass
    base = importlib.import_module("Cryptodome")          # python3-pycryptodome (Debian)
    pkg = sys.modules.setdefault("Crypto", types.ModuleType("Crypto"))
    pkg.__path__ = []                                     # namespace stub: nothing else importable under it
    pkg.__task_mesh_alias__ = base.__name__
    for name in _ALIASES:
        mod = importlib.import_module(f"Cryptodome.{name}")
        sys.modules[f"Crypto.{name}"] = mod
        parent, _, leaf = f"Crypto.{name}".rpartition(".")
        setattr(sys.modules[parent], leaf, mod)
    return "Cryptodome"


def quiet_logger() -> logging.Logger:
    lg = logging.getLogger("meshcore")
    lg.setLevel(logging.WARNING)
    lg.propagate = False
    if not any(isinstance(h, logging.NullHandler) for h in lg.handlers):
        lg.addHandler(logging.NullHandler())
    return lg


def import_meshcore():
    ensure_crypto()
    quiet_logger()
    import meshcore  # noqa: F401  (bundled under task_mesh/_vendor)
    quiet_logger()
    return meshcore
