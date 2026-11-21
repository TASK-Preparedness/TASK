# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Frequency overlays (M3 framework). RECEIVE-ONLY reference data; nothing here can transmit.

Datasets are external, versioned JSON files (schema "task-sdr-overlay/1", see
schema/overlay-v1.schema.json) loaded at runtime from
    /usr/share/task-sdr/overlays/*.json            (system, read-only, shipped by data packages)
    ~/.local/share/task-sdr/overlays/*.json        (user; also holds the user's own annotations)
so data can be added or updated without rebuilding task-sdr. task-sdr itself ships NO dataset.

Validation is strict: integer Hz only, explicit bounds, ISO dates, https source URLs, no unknown keys, no
duplicate JSON keys, no NaN/Infinity, size and item limits. A file that fails ANY rule is rejected as a whole
(never partially loaded) and the reason is reported. Listing a frequency does not mean it is in use, and
receive capability is not transmit authorization.
"""

import datetime as dt
import hashlib
import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from task_comms import paths

SCHEMA = "task-sdr-overlay/1"
TYPES = ("allocation", "channel_plan", "station_record", "user_annotation")
TYPE_LABEL = {"allocation": "Allocation", "channel_plan": "Channel plan", "station_record": "Station record",
              "user_annotation": "User annotation"}
SYSTEM_DIR = Path("/usr/share/task-sdr/overlays")
USER_ID = "user-annotations"
USER_FILE = "user-annotations.json"
MIN_HZ, MAX_HZ = 1, 6_000_000_000          # 1 Hz .. 6 GHz (covers every supported receiver with margin)
MAX_BANDWIDTH_HZ = 1_000_000_000
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 5000
MAX_TEXT = 200
NOTE_NOT_ACTIVE = "Listed does not mean active: an entry only says a frequency is allocated, planned or recorded."
NOTE_NO_TX = "Receive capability is not transmit authorization. SDR Studio is receive only."

TOP_REQUIRED = ("schema", "id", "title", "type", "version", "source", "publication_date", "retrieved",
                "last_verified", "items")
TOP_OPTIONAL = ("stale_after_days", "attribution", "example", "notes")
SOURCE_KEYS_REQUIRED = ("agency", "citation")
SOURCE_KEYS_OPTIONAL = ("url",)
ITEM_COMMON = ("kind", "label")
ITEM_OPTIONAL = ("ref", "notes", "tags")
RANGE_KEYS = ("start_hz", "end_hz")
MARKER_KEYS = ("freq_hz",)
MARKER_OPTIONAL = ("bandwidth_hz",)
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+~-]{0,31}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class OverlayError(ValueError):
    """A dataset failed validation. The message says where and why."""


@dataclass(frozen=True)
class Item:
    kind: str                       # "range" | "marker"
    label: str
    start_hz: int                   # marker: freq - bw/2 (or freq); range: start
    end_hz: int                     # marker: freq + bw/2 (or freq); range: end
    freq_hz: int | None = None      # markers only
    bandwidth_hz: int | None = None
    ref: str = ""
    notes: str = ""
    tags: tuple = ()

    def tune_hz(self):
        """Receive frequency offered when the user asks to tune: the marker frequency, or a range's centre."""
        return self.freq_hz if self.freq_hz is not None else (self.start_hz + self.end_hz) // 2

    def to_json(self):
        d = {"kind": self.kind, "label": self.label}
        if self.kind == "marker":
            d["freq_hz"] = self.freq_hz
            if self.bandwidth_hz is not None:
                d["bandwidth_hz"] = self.bandwidth_hz
        else:
            d["start_hz"], d["end_hz"] = self.start_hz, self.end_hz
        for k in ("ref", "notes"):
            if getattr(self, k):
                d[k] = getattr(self, k)
        if self.tags:
            d["tags"] = list(self.tags)
        return d


@dataclass
class Dataset:
    id: str
    title: str
    type: str
    version: str
    source: dict
    publication_date: dt.date | None
    retrieved: dt.date | None
    last_verified: dt.date | None
    items: list
    stale_after_days: int = 365
    attribution: str = ""
    example: bool = False
    notes: str = ""
    origin: str = ""                # "system" | "user"
    path: str = ""
    sha256: str = ""

    def status(self, today=None):
        """Flags shown in the UI. 'unverified' = never verified by a person; 'stale' = verified too long ago."""
        today = today or dt.date.today()
        flags = []
        if self.example:
            flags.append("example")
        if self.last_verified is None:
            flags.append("unverified")
        elif (today - self.last_verified).days > self.stale_after_days:
            flags.append("stale")
        if self.origin == "user":
            flags.append("user")
        return flags


# ------------------------------------------------------------------ validation helpers
def _reject_dupes(pairs):
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise OverlayError(f"duplicate JSON key {k!r}")
        seen[k] = v
    return seen


def _no_constants(name):
    raise OverlayError(f"non-finite number {name} is not allowed")


def _keys(obj, where, required, optional=()):
    if not isinstance(obj, dict):
        raise OverlayError(f"{where}: must be an object")
    missing = [k for k in required if k not in obj]
    if missing:
        raise OverlayError(f"{where}: missing {', '.join(missing)}")
    unknown = sorted(set(obj) - set(required) - set(optional))
    if unknown:
        raise OverlayError(f"{where}: unknown key(s) {', '.join(unknown)}")


def _text(v, where, *, allow_empty=False, maxlen=MAX_TEXT):
    if not isinstance(v, str):
        raise OverlayError(f"{where}: must be text")
    if not allow_empty and not v.strip():
        raise OverlayError(f"{where}: must not be empty")
    if len(v) > maxlen:
        raise OverlayError(f"{where}: longer than {maxlen} characters")
    if any(ord(c) < 32 and c not in "\t" for c in v):
        raise OverlayError(f"{where}: contains control characters")
    return v


def _hz(v, where, lo=MIN_HZ, hi=MAX_HZ):
    # bool is an int subclass; floats (even 146.52e6) are refused so the unit is unambiguous: integer Hz
    if isinstance(v, bool) or not isinstance(v, int):
        raise OverlayError(f"{where}: must be an integer number of Hz (got {type(v).__name__} {v!r})")
    if not lo <= v <= hi:
        raise OverlayError(f"{where}: {v} Hz is outside {lo}..{hi} Hz")
    return v


def _date(v, where, *, nullable, today):
    if v is None:
        if nullable:
            return None
        raise OverlayError(f"{where}: required (YYYY-MM-DD)")
    if not isinstance(v, str) or not DATE_RE.match(v):
        raise OverlayError(f"{where}: must be a date YYYY-MM-DD")
    try:
        d = dt.date.fromisoformat(v)
    except ValueError as exc:
        raise OverlayError(f"{where}: invalid date {v!r} ({exc})") from None
    if d > today:
        raise OverlayError(f"{where}: {v} is in the future")
    return d


def _item(raw, where):
    if not isinstance(raw, dict):
        raise OverlayError(f"{where}: must be an object")
    kind = raw.get("kind")
    if kind == "range":
        _keys(raw, where, ITEM_COMMON + RANGE_KEYS, ITEM_OPTIONAL)
        s, e = _hz(raw["start_hz"], f"{where}.start_hz"), _hz(raw["end_hz"], f"{where}.end_hz")
        if s >= e:
            raise OverlayError(f"{where}: start_hz {s} must be below end_hz {e}")
        f = bw = None
    elif kind == "marker":
        _keys(raw, where, ITEM_COMMON + MARKER_KEYS, ITEM_OPTIONAL + MARKER_OPTIONAL)
        f = _hz(raw["freq_hz"], f"{where}.freq_hz")
        bw = raw.get("bandwidth_hz")
        if bw is not None:
            bw = _hz(bw, f"{where}.bandwidth_hz", 1, MAX_BANDWIDTH_HZ)
            if f - bw // 2 < MIN_HZ or f + bw // 2 > MAX_HZ:
                raise OverlayError(f"{where}: bandwidth {bw} Hz around {f} Hz leaves {MIN_HZ}..{MAX_HZ} Hz")
        s, e = (f - bw // 2, f + bw // 2) if bw else (f, f)
    else:
        raise OverlayError(f"{where}.kind: must be 'range' or 'marker' (got {kind!r})")
    label = _text(raw["label"], f"{where}.label")
    tags = raw.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 16 or not all(isinstance(t, str) and TAG_RE.match(t) for t in tags):
        raise OverlayError(f"{where}.tags: up to 16 lower-case tags [a-z0-9_-]")
    return Item(kind, label, s, e, f, bw, _text(raw.get("ref", ""), f"{where}.ref", allow_empty=True),
                _text(raw.get("notes", ""), f"{where}.notes", allow_empty=True, maxlen=1000), tuple(tags))


def parse_dataset(data, *, today=None, origin="", path="", sha256=""):
    """Validate a decoded JSON document. Raises OverlayError on the first problem."""
    today = today or dt.date.today()
    _keys(data, "dataset", TOP_REQUIRED, TOP_OPTIONAL)
    if data["schema"] != SCHEMA:
        raise OverlayError(f"schema: expected {SCHEMA!r}, got {data['schema']!r}")
    if not isinstance(data["id"], str) or not ID_RE.match(data["id"]):
        raise OverlayError("id: 1-64 characters [a-z0-9._-], starting with a letter or digit")
    if data["type"] not in TYPES:
        raise OverlayError(f"type: must be one of {', '.join(TYPES)} (got {data['type']!r})")
    if not isinstance(data["version"], str) or not VERSION_RE.match(data["version"]):
        raise OverlayError("version: 1-32 characters [0-9A-Za-z.+~-]")
    title = _text(data["title"], "title")
    user = data["type"] == "user_annotation"
    src = data["source"]
    _keys(src, "source", SOURCE_KEYS_REQUIRED, SOURCE_KEYS_OPTIONAL)
    _text(src["agency"], "source.agency")
    _text(src["citation"], "source.citation", allow_empty=user)
    if "url" in src:
        u = _text(src["url"], "source.url", maxlen=500)
        if not re.match(r"^https://[A-Za-z0-9.-]+(/[^\s]*)?$", u):
            raise OverlayError("source.url: must be an https:// URL")
    elif not user:
        raise OverlayError("source.url: required for non-user datasets")
    pub = _date(data["publication_date"], "publication_date", nullable=user, today=today)
    ret = _date(data["retrieved"], "retrieved", nullable=user, today=today)
    ver = _date(data["last_verified"], "last_verified", nullable=True, today=today)
    if pub and ret and ret < pub:
        raise OverlayError("retrieved: earlier than publication_date")
    stale = data.get("stale_after_days", 365)
    if isinstance(stale, bool) or not isinstance(stale, int) or not 1 <= stale <= 3650:
        raise OverlayError("stale_after_days: integer 1..3650")
    example = data.get("example", False)
    if not isinstance(example, bool):
        raise OverlayError("example: true or false")
    items = data["items"]
    if not isinstance(items, list):
        raise OverlayError("items: must be a list")
    if len(items) > MAX_ITEMS:
        raise OverlayError(f"items: more than {MAX_ITEMS}")
    parsed, seen = [], set()
    for i, raw in enumerate(items):
        it = _item(raw, f"items[{i}]")
        key = (it.kind, it.start_hz, it.end_hz, it.freq_hz, it.label)
        if key in seen:
            raise OverlayError(f"items[{i}]: duplicate of an earlier item")
        seen.add(key)
        parsed.append(it)
    return Dataset(data["id"], title, data["type"], data["version"], dict(src), pub, ret, ver, parsed, stale,
                   _text(data.get("attribution", ""), "attribution", allow_empty=True, maxlen=1000), example,
                   _text(data.get("notes", ""), "notes", allow_empty=True, maxlen=2000), origin, path, sha256)


def load_file(path, *, today=None, origin=""):
    """Read and validate one file. Regular files only, size-limited, strict JSON."""
    p = Path(path)
    try:
        st = p.lstat()
    except OSError as exc:
        raise OverlayError(f"cannot read: {exc.strerror}") from None
    if not p.is_file() or p.is_symlink():
        raise OverlayError("not a regular file (symlinks are not followed)")
    if st.st_size > MAX_FILE_BYTES:
        raise OverlayError(f"file is larger than {MAX_FILE_BYTES} bytes")
    raw = p.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise OverlayError("not UTF-8 text") from None
    try:
        data = json.loads(text, object_pairs_hook=_reject_dupes, parse_constant=_no_constants)
    except OverlayError:
        raise
    except ValueError as exc:
        raise OverlayError(f"invalid JSON: {exc}") from None
    return parse_dataset(data, today=today, origin=origin, path=str(p), sha256=hashlib.sha256(raw).hexdigest())


def user_dir():
    return paths.data_dir("task-sdr") / "overlays"


def search_dirs():
    return [("system", SYSTEM_DIR), ("user", user_dir())]


@dataclass
class LoadResult:
    datasets: list = field(default_factory=list)
    errors: list = field(default_factory=list)          # [(path, reason)]


def load_all(dirs=None, *, today=None):
    """Load every *.json from the search dirs. Bad files are reported, never partially used. A user file may
    not reuse the id of a system dataset (no silent shadowing)."""
    res, ids = LoadResult(), {}
    for origin, d in (dirs if dirs is not None else search_dirs()):
        d = Path(d)
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            try:
                ds = load_file(p, today=today, origin=origin)
                if origin != "user" and ds.type == "user_annotation":
                    raise OverlayError("user_annotation datasets are only accepted from the user directory")
                if ds.id in ids:
                    raise OverlayError(f"id {ds.id!r} already loaded from {ids[ds.id]}")
            except OverlayError as exc:
                res.errors.append((str(p), str(exc)))
                continue
            ids[ds.id] = str(p)
            res.datasets.append(ds)
    return res


class BackgroundLoader:
    """Runs load_all on a worker thread; callback(result) is called from that thread (UI marshals it)."""

    def __init__(self, callback, dirs=None):
        self.callback, self.dirs = callback, dirs
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name="overlay-loader", daemon=True)
        self.thread.start()
        return self.thread

    def _run(self):
        try:
            res = load_all(self.dirs)
        except Exception as exc:  # noqa: BLE001  (never let a loader crash the app)
            res = LoadResult(errors=[("<loader>", f"unexpected error: {exc}")])
        self.callback(res)


# ------------------------------------------------------------------ toggles (separate file; prefs untouched)
def toggles_path():
    return paths.config_dir("task-sdr") / "overlays.json"


def load_toggles(path=None):
    p = Path(path or toggles_path())
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(d, dict):
        return {}
    return {k: v for k, v in d.items() if isinstance(k, str) and ID_RE.match(k) and isinstance(v, bool)}


def _atomic_write(path, text):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(p.parent, 0o700)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def save_toggles(toggles, path=None):
    _atomic_write(path or toggles_path(), json.dumps(dict(sorted(toggles.items())), indent=1))


# ------------------------------------------------------------------ queries
class OverlaySet:
    """Loaded datasets + toggles. Overlays are OFF until the user turns them on (nothing appears unasked)."""

    def __init__(self, datasets=(), toggles=None):
        self.datasets = {d.id: d for d in datasets}
        self.toggles = dict(toggles or {})

    def enabled(self, ds_id):
        return self.toggles.get(ds_id, False)

    def set_enabled(self, ds_id, on):
        if ds_id not in self.datasets:
            raise KeyError(ds_id)
        self.toggles[ds_id] = bool(on)

    def visible(self, lo_hz, hi_hz):
        """[(dataset, item)] of ENABLED datasets that intersect [lo, hi]."""
        out = []
        for d in self.datasets.values():
            if self.enabled(d.id):
                out.extend((d, it) for it in d.items if it.end_hz >= lo_hz and it.start_hz <= hi_hz)
        return out

    def search(self, text="", types=None, enabled_only=False, limit=500):
        """Case-insensitive match on label/ref/notes/tags/dataset title, or a frequency in MHz/kHz/Hz."""
        q = text.strip().lower()
        f = _parse_freq(q)
        out = []
        for d in self.datasets.values():
            if types and d.type not in types:
                continue
            if enabled_only and not self.enabled(d.id):
                continue
            for it in d.items:
                hay = " ".join((it.label, it.ref, it.notes, " ".join(it.tags), d.title)).lower()
                if not q or q in hay or (f is not None and it.start_hz <= f <= it.end_hz):
                    out.append((d, it))
                    if len(out) >= limit:
                        return out
        return out


def _parse_freq(q):
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(ghz|mhz|khz|hz)?", q)
    if not m:
        return None
    mult = {"ghz": 10**9, "mhz": 10**6, "khz": 10**3, "hz": 1, None: 10**6}[m.group(2)]
    return int(round(float(m.group(1)) * mult))


# ------------------------------------------------------------------ user annotations
class UserAnnotations:
    """The user's own markers/ranges in ~/.local/share/task-sdr/overlays/user-annotations.json (0600).
    Every change is validated with the same strict rules before it is written atomically."""

    def __init__(self, directory=None):
        self.path = Path(directory or user_dir()) / USER_FILE
        self.items = []
        if self.path.exists():
            self.items = list(load_file(self.path, origin="user").items)

    def _doc(self):
        return {"schema": SCHEMA, "id": USER_ID, "title": "My annotations", "type": "user_annotation",
                "version": "1", "source": {"agency": "user", "citation": ""}, "publication_date": None,
                "retrieved": None, "last_verified": None, "items": [i.to_json() for i in self.items]}

    def _commit(self, items):
        doc = self._doc()
        doc["items"] = [i.to_json() for i in items]
        parse_dataset(doc, origin="user")           # validates; raises OverlayError before anything is written
        _atomic_write(self.path, json.dumps(doc, indent=1))
        self.items = list(items)

    def add_marker(self, freq_hz, label, bandwidth_hz=None, notes=""):
        raw = {"kind": "marker", "label": label, "freq_hz": freq_hz}
        if bandwidth_hz is not None:
            raw["bandwidth_hz"] = bandwidth_hz
        if notes:
            raw["notes"] = notes
        it = _item(raw, "new annotation")
        self._commit(self.items + [it])
        return it

    def add_range(self, start_hz, end_hz, label, notes=""):
        raw = {"kind": "range", "label": label, "start_hz": start_hz, "end_hz": end_hz}
        if notes:
            raw["notes"] = notes
        it = _item(raw, "new annotation")
        self._commit(self.items + [it])
        return it

    def edit_label(self, index, label):
        it = self.items[index]
        raw = it.to_json()
        raw["label"] = label
        new = list(self.items)
        new[index] = _item(raw, f"annotation {index}")
        self._commit(new)

    def remove(self, index):
        new = list(self.items)
        del new[index]
        self._commit(new)
