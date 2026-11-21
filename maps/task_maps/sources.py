# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Tile source definitions and the offline-download policy.

Definitions are TOML files (schema 1): package ``/usr/share/task-maps/sources.d/*.toml`` and user
``~/.config/task-maps/sources.d/*.toml``. A user file may add new ids but may not replace a
package id.

Policy (``download_permission``):
* hosts of the OpenStreetMap Foundation standard tile servers are **always refused** for bulk /
  offline download (https://operations.osmfoundation.org/policies/tiles/ §4), whatever a
  definition says;
* a package source may be downloaded only if ``offline_download_permitted = true`` *and* it cites
  evidence URLs and a ``verified_on`` date;
* a user source may be downloaded only if ``offline_download_permitted = true`` *and*
  ``user_attests_permission = true`` (the user states they have permission, e.g. their own tile
  server on the LAN);
* sources needing an API key are only usable once a key is stored in
  ``~/.config/task-maps/keys.toml`` (mode 0600). Keys are substituted at request time and never
  logged (``redact``).
"""

import os
import re
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from task_maps import atomic, paths

ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,47}$")
REFUSED_HOSTS = ("tile.openstreetmap.org",)
REFUSED_REASON = ("OpenStreetMap's standard tile servers forbid bulk downloading and offline use "
                  "(OSMF Tile Usage Policy §4, https://operations.osmfoundation.org/policies/tiles/)")
KEYS = {"schema", "id", "name", "url", "mechanism", "format", "attribution", "license", "usage_policy_url",
        "offline_download_permitted", "evidence", "evidence_urls", "verified_on", "rate_limit",
        "max_concurrency", "min_zoom", "max_zoom", "max_tiles_per_job", "user_agent_required",
        "api_key_required", "enabled", "coverage", "avg_tile_bytes", "user_attests_permission", "notes"}
HARD_MAX_RATE = 10.0
HARD_MAX_CONCURRENCY = 4
HARD_MAX_TILES = 500_000
MAX_FILE = 64 * 1024


class SourceError(ValueError):
    pass


@dataclass
class Source:
    id: str
    name: str
    url: str
    trust: str = "package"            # package | user
    path: str = ""
    mechanism: str = "xyz"            # xyz ({y} from the top) | tms ({y} from the bottom)
    format: str = "auto"
    attribution: str = ""
    license: str = ""
    usage_policy_url: str = ""
    offline_download_permitted: bool = False
    evidence: str = ""
    evidence_urls: list = field(default_factory=list)
    verified_on: str = ""
    rate_limit: float = 1.0
    max_concurrency: int = 1
    min_zoom: int = 0
    max_zoom: int = 16
    max_tiles_per_job: int = 50_000
    user_agent_required: bool = True
    api_key_required: bool = False
    enabled: bool = True
    coverage: str = ""
    avg_tile_bytes: int = 20_000
    user_attests_permission: bool = False
    notes: str = ""

    @property
    def host(self) -> str:
        return (urlsplit(self.url.replace("{", "").replace("}", "")).hostname or "").lower()

    def tile_url(self, z, x, y, api_key="") -> str:
        row = (2 ** z - 1 - y) if self.mechanism == "tms" else y
        return (self.url.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(row))
                .replace("{api_key}", api_key))

    def redact(self, text: str, api_key: str = "") -> str:
        return text.replace(api_key, "***") if api_key else text


def _bool(doc, key, default):
    v = doc.get(key, default)
    if not isinstance(v, bool):
        raise SourceError(f"'{key}' must be true or false")
    return v


def _num(doc, key, default, lo, hi, kind=float):
    v = doc.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (kind is int and not isinstance(v, int)):
        raise SourceError(f"'{key}' must be a number")
    if not lo <= v <= hi:
        raise SourceError(f"'{key}' must be between {lo} and {hi}")
    return kind(v)


def _str(doc, key, maxlen, required=False):
    v = doc.get(key, "")
    if not isinstance(v, str):
        raise SourceError(f"'{key}' must be a string")
    if required and not v.strip():
        raise SourceError(f"'{key}' is required")
    if len(v) > maxlen:
        raise SourceError(f"'{key}' is longer than {maxlen} characters")
    return v.strip()


def parse(doc: dict, trust="package", path="") -> Source:
    unknown = set(doc) - KEYS
    if unknown:
        raise SourceError(f"unknown key(s): {', '.join(sorted(unknown))}")
    if doc.get("schema") != 1:
        raise SourceError("'schema' must be 1")
    sid = _str(doc, "id", 48, True)
    if not ID_RE.match(sid):
        raise SourceError("'id' must match [a-z][a-z0-9-]{1,47}")
    url = _str(doc, "url", 512, True)
    parts = urlsplit(url.replace("{", "").replace("}", ""))
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise SourceError("'url' must be an http(s) URL template")
    if parts.scheme == "http" and trust == "package":
        raise SourceError("package sources must use https")
    for ph in ("{z}", "{x}", "{y}"):
        if ph not in url:
            raise SourceError(f"'url' must contain {ph}")
    s = Source(id=sid, name=_str(doc, "name", 80, True), url=url, trust=trust, path=str(path))
    s.mechanism = _str(doc, "mechanism", 8) or "xyz"
    if s.mechanism not in ("xyz", "tms"):
        raise SourceError("'mechanism' must be xyz or tms")
    s.format = _str(doc, "format", 8) or "auto"
    if s.format not in ("auto", "png", "jpg", "webp"):
        raise SourceError("'format' must be auto, png, jpg or webp")
    s.attribution = _str(doc, "attribution", 400, True)
    s.license = _str(doc, "license", 1000)
    s.usage_policy_url = _str(doc, "usage_policy_url", 300)
    s.offline_download_permitted = _bool(doc, "offline_download_permitted", False)
    s.evidence = _str(doc, "evidence", 2000)
    ev = doc.get("evidence_urls", [])
    if not isinstance(ev, list) or not all(isinstance(u, str) and u.startswith("https://") for u in ev):
        raise SourceError("'evidence_urls' must be a list of https URLs")
    s.evidence_urls = list(ev)
    s.verified_on = _str(doc, "verified_on", 10)
    if s.verified_on:
        try:
            date.fromisoformat(s.verified_on)
        except ValueError:
            raise SourceError("'verified_on' must be YYYY-MM-DD") from None
    s.rate_limit = _num(doc, "rate_limit", 1.0, 0.05, HARD_MAX_RATE)
    s.max_concurrency = _num(doc, "max_concurrency", 1, 1, HARD_MAX_CONCURRENCY, int)
    s.min_zoom = _num(doc, "min_zoom", 0, 0, 22, int)
    s.max_zoom = _num(doc, "max_zoom", 16, 0, 22, int)
    if s.min_zoom > s.max_zoom:
        raise SourceError("'min_zoom' is greater than 'max_zoom'")
    s.max_tiles_per_job = _num(doc, "max_tiles_per_job", 50_000, 1, HARD_MAX_TILES, int)
    s.user_agent_required = _bool(doc, "user_agent_required", True)
    s.api_key_required = _bool(doc, "api_key_required", False)
    if s.api_key_required and "{api_key}" not in url:
        raise SourceError("'api_key_required' needs an {api_key} placeholder in 'url'")
    s.enabled = _bool(doc, "enabled", True)
    s.coverage = _str(doc, "coverage", 300)
    s.avg_tile_bytes = _num(doc, "avg_tile_bytes", 20_000, 500, 1_000_000, int)
    s.user_attests_permission = _bool(doc, "user_attests_permission", False)
    if s.user_attests_permission and trust == "package":
        raise SourceError("'user_attests_permission' is only allowed in user source files")
    s.notes = _str(doc, "notes", 1000)
    return s


def host_refused(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(host == h or host.endswith("." + h) for h in REFUSED_HOSTS)


def download_permission(s: Source, api_key: str = ""):
    """(allowed: bool, reason: str) for bulk/offline download from this source."""
    if host_refused(s.host):
        return False, REFUSED_REASON
    if not s.enabled:
        return False, "this source is disabled"
    if not s.offline_download_permitted:
        return False, ("the provider's terms do not permit offline/bulk download (or could not be verified); "
                       "use your own tile server or import an MBTiles file")
    if s.trust == "package" and not (s.evidence_urls and s.verified_on):
        return False, "permission is not backed by cited terms and a verification date"
    if s.trust == "user" and not s.user_attests_permission:
        return False, "set user_attests_permission = true in your source file to confirm you have permission"
    if s.api_key_required and not api_key:
        return False, "this source needs an API key (Download → API key…)"
    return True, "permitted" + (" (user-attested)" if s.trust == "user" else f" (terms verified {s.verified_on})")


@dataclass
class Catalog:
    sources: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)   # (path, message)

    def ordered(self):
        return sorted(self.sources.values(), key=lambda s: (s.trust != "package", s.name.casefold()))


def _read_dir(d: Path, trust: str, cat: Catalog):
    try:
        names = sorted(n for n in os.listdir(d) if n.endswith(".toml") and not n.startswith("."))
    except OSError:
        return
    for n in names[:128]:
        p = d / n
        try:
            if p.is_symlink() or not p.is_file():
                raise SourceError("not a regular file")
            if p.stat().st_size > MAX_FILE:
                raise SourceError("file too large")
            with open(p, "rb") as fh:
                s = parse(tomllib.load(fh), trust, p)
        except (OSError, tomllib.TOMLDecodeError, SourceError) as exc:
            cat.problems.append((str(p), str(exc)))
            continue
        if s.id in cat.sources:
            cat.problems.append((str(p), f"id {s.id!r} already defined by {cat.sources[s.id].path}; ignored"))
            continue
        cat.sources[s.id] = s


def load(system_dir=None, user_dir=None) -> Catalog:
    cat = Catalog()
    _read_dir(Path(system_dir or paths.system_sources_dir()), "package", cat)
    _read_dir(Path(user_dir or paths.user_sources_dir()), "user", cat)
    return cat


# ---------------------------------------------------------------- API keys (user config, 0600)

def keys_path() -> Path:
    return paths.config_dir() / "keys.toml"


def load_keys(path=None) -> dict:
    path = Path(path or keys_path())
    try:
        with open(path, "rb") as fh:
            doc = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    keys = doc.get("keys", {})
    return {k: v for k, v in keys.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(keys, dict) else {}


def _toml_str(v: str) -> str:
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def save_key(source_id: str, key: str, path=None):
    if not ID_RE.match(source_id):
        raise SourceError("bad source id")
    if any(ord(c) < 32 or c == "\x7f" for c in key) or len(key) > 512:
        raise SourceError("invalid key")
    path = Path(path or keys_path())
    keys = load_keys(path)
    if key:
        keys[source_id] = key
    else:
        keys.pop(source_id, None)
    body = "# task-maps API keys (never logged). Mode 0600.\n[keys]\n" + \
        "".join(f"{k} = {_toml_str(v)}\n" for k, v in sorted(keys.items()))
    atomic.write_text(path, body, 0o600)
