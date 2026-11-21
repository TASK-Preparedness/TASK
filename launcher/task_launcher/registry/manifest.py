# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""T.A.S.K. launcher app manifest, schema v1 (MANIFEST-SPEC.md). TOML, parsed with stdlib tomllib.

A manifest is data only. Nothing in it is executed by the launcher except the ``launch.exec``
argv, which is started directly (no shell) after the executable checks in execcheck.py.
"""

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from task_launcher import icons
from task_launcher.registry.execcheck import check_executable

MAX_FILE_BYTES = 64 * 1024
MAX_ARGS = 64
MAX_ARG_LEN = 4096
ID_RE = re.compile(r"^[a-z][a-z0-9]*(\.[a-z][a-z0-9-]*){1,3}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
ROLES = ("public", "operator", "administrator")
BUILTINS = ("system", "app-manager", "files", "devices", "library", "radio", "weather", "medical")
# builtins that prefer an external app (exec) and fall back to the built-in window when it is missing
EXEC_FALLBACK_BUILTINS = ("devices", "radio", "library")
# Platform 0.2.0 additions (all optional, additive): readiness, status_note, [launch.labels], [[actions]].
READINESS_PROBES = ("gps", "rtl-sdr", "mesh", "kiwix", "direwolf", "weather", "medical")
TOP_KEYS = {"manifest_version", "id", "name", "version", "description", "icon", "order", "status",
            "min_platform", "enabled", "single_instance", "min_role", "roadmap", "launch", "requires",
            "readiness", "status_note", "actions"}
LAUNCH_KEYS = {"exec", "exec_alternatives", "builtin", "on_reactivate", "labels"}
ACTION_KEYS = {"id", "label", "exec", "terminal"}
ACTION_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
MAX_ACTIONS = 8
REQUIRES_KEYS = {"hardware", "core_capabilities", "core_min_version", "debian"}
ICON_DIRS = (Path("/usr/share/task-launcher/icons"), Path("/usr/share/icons"), Path("/usr/share/pixmaps"))
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class ManifestError(ValueError):
    pass


@dataclass
class Manifest:
    id: str
    name: str
    version: str
    description: str = ""
    icon: object = "shapes"          # Lucide name (str) or Path to a validated SVG
    order: int = 10000
    status: str = "available"        # available | planned
    min_platform: str = "0.0.0"
    enabled: bool = True
    single_instance: bool = True
    min_role: str = "public"
    roadmap: str = ""
    exec: list = None                # argv (absolute program path first)
    exec_alternatives: list = field(default_factory=list)
    builtin: str = None
    on_reactivate: str = "notify"    # notify | relaunch
    hardware: list = field(default_factory=list)
    core_capabilities: list = field(default_factory=list)
    core_min_version: str = None
    debian: list = field(default_factory=list)
    path: Path = None
    trust: str = "user"              # package | admin | user
    warnings: list = field(default_factory=list)
    readiness: str = None            # name of a built-in readiness probe (READINESS_PROBES)
    status_note: str = ""            # short text after "Available — " for built-in windows
    labels: dict = field(default_factory=dict)   # absolute program path -> label of that variant
    actions: list = field(default_factory=list)  # [Action]

    def candidates(self):
        return ([self.exec] if self.exec else []) + list(self.exec_alternatives)

    def label_for(self, argv):
        if not argv:
            return ""
        return self.labels.get(argv[0], "")

    def resolve_exec(self):
        """(argv or None, status, reason): the first exec candidate that passes the checks."""
        candidates = self.candidates()
        first_failure = None
        missing = []
        for argv in candidates:
            status, reason = check_executable(argv[0])
            if status == "ok":
                return list(argv), "ok", ""
            if status == "missing":
                name = self.labels.get(argv[0]) or argv[0]
                if name not in missing:
                    missing.append(name)
            if first_failure is None or (first_failure[0] == "missing" and status != "missing"):
                first_failure = (status, reason)
        if first_failure is None:
            return None, "invalid", "no executable"
        if first_failure[0] == "missing" and len(candidates) > 1:
            return None, "missing", "not installed: " + ", ".join(missing)
        return None, first_failure[0], first_failure[1]


@dataclass
class Action:
    """A secondary action (e.g. "GPS monitor (gpsmon)"). Never a shell; terminal apps are wrapped in
    the detected terminal emulator (registry/desktop.find_terminal) at launch time."""
    id: str
    label: str
    exec: list
    terminal: bool = False


def version_tuple(text):
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in m.groups()) if m else None


def _str(doc, key, limit, required=False, default=""):
    if key not in doc:
        if required:
            raise ManifestError(f"missing required key '{key}'")
        return default
    value = doc[key]
    if not isinstance(value, str):
        raise ManifestError(f"'{key}' must be a string")
    if len(value) > limit:
        raise ManifestError(f"'{key}' longer than {limit} characters")
    if _CONTROL.search(value):
        raise ManifestError(f"'{key}' contains control characters")
    return value


def _strlist(value, key, limit=32, item_limit=128):
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ManifestError(f"'{key}' must be a list of strings")
    if len(value) > limit or any(len(x) > item_limit for x in value):
        raise ManifestError(f"'{key}' too long")
    return list(value)


def _argv(value, key):
    if not isinstance(value, list) or not value:
        raise ManifestError(f"'{key}' must be a non-empty list of strings (argv)")
    if not all(isinstance(x, str) for x in value):
        raise ManifestError(f"'{key}' must contain only strings")
    if len(value) > MAX_ARGS or any(len(x) > MAX_ARG_LEN for x in value):
        raise ManifestError(f"'{key}' too long")
    if any("\x00" in x for x in value):
        raise ManifestError(f"'{key}' contains NUL")
    if not value[0].startswith("/"):
        raise ManifestError(f"'{key}[0]' must be an absolute path")
    return list(value)


def _labels(value, candidates):
    if not isinstance(value, dict):
        raise ManifestError("[launch.labels] must be a table of program path = label")
    known = {argv[0] for argv in candidates}
    out = {}
    for path, label in value.items():
        if path not in known:
            raise ManifestError(f"[launch.labels] key {path!r} is not the program of exec or an alternative")
        if not isinstance(label, str) or not label.strip() or len(label) > 60 or _CONTROL.search(label):
            raise ManifestError(f"[launch.labels] value for {path!r} must be a string of 1-60 characters")
        out[path] = label.strip()
    return out


def _actions(value):
    if not isinstance(value, list) or len(value) > MAX_ACTIONS:
        raise ManifestError(f"'actions' must be an array of tables (at most {MAX_ACTIONS})")
    out, seen = [], set()
    for item in value:
        if not isinstance(item, dict):
            raise ManifestError("each [[actions]] entry must be a table")
        unknown = set(item) - ACTION_KEYS
        if unknown:
            raise ManifestError(f"unknown [[actions]] key(s): {', '.join(sorted(unknown))}")
        aid = _str(item, "id", 32, required=True)
        if not ACTION_ID_RE.match(aid) or aid in seen:
            raise ManifestError(f"invalid or duplicate action id {aid!r}")
        seen.add(aid)
        label = _str(item, "label", 40, required=True).strip()
        if not label:
            raise ManifestError("action 'label' is empty")
        if "exec" not in item:
            raise ManifestError(f"action {aid!r} needs 'exec'")
        terminal = item.get("terminal", False)
        if not isinstance(terminal, bool):
            raise ManifestError("action 'terminal' must be true or false")
        out.append(Action(aid, label, _argv(item["exec"], f"actions.{aid}.exec"), terminal))
    return out


def _icon(value, manifest_dir: Path, warnings: list):
    if value is None:
        return "shapes"
    if not isinstance(value, str) or len(value) > 512:
        warnings.append("icon ignored: must be a string")
        return "shapes"
    if re.fullmatch(r"[a-z0-9-]{1,64}", value):
        if icons.lucide_path(value).is_file():
            return value
        warnings.append(f"icon ignored: no bundled icon named {value!r}")
        return "shapes"
    candidate = Path(value) if value.startswith("/") else manifest_dir / value
    try:
        real = candidate.resolve(strict=True)
    except OSError:
        warnings.append(f"icon ignored: file not found: {value}")
        return "shapes"
    allowed = [manifest_dir.resolve()] + [d for d in ICON_DIRS]
    if not any(real == d or d in real.parents for d in allowed):
        warnings.append(f"icon ignored: path outside the manifest directory and icon directories: {value}")
        return "shapes"
    if real.suffix.lower() != ".svg":
        warnings.append("icon ignored: only SVG icons are supported")
        return "shapes"
    try:
        if not icons.svg_is_safe(real.read_bytes()):
            warnings.append("icon ignored: SVG too large or contains scripts/external references")
            return "shapes"
    except OSError:
        warnings.append("icon ignored: unreadable")
        return "shapes"
    return real


def parse_text(text: str, path: Path = None, trust: str = "user") -> Manifest:
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError(f"malformed TOML: {exc}") from None
    return parse_doc(doc, path, trust)


def parse_doc(doc: dict, path: Path = None, trust: str = "user") -> Manifest:
    if doc.get("manifest_version") != 1 or isinstance(doc.get("manifest_version"), bool):
        raise ManifestError("unsupported or missing manifest_version (expected 1)")
    unknown = set(doc) - TOP_KEYS
    if unknown:
        raise ManifestError(f"unknown key(s): {', '.join(sorted(unknown))}")
    warnings = []
    mid = _str(doc, "id", 64, required=True)
    if not ID_RE.match(mid):
        raise ManifestError(f"invalid id {mid!r} (expected e.g. 'task.system' or 'publisher.app')")
    name = _str(doc, "name", 40, required=True).strip()
    if not name:
        raise ManifestError("'name' is empty")
    version = _str(doc, "version", 64, required=True)
    if not VERSION_RE.match(version):
        raise ManifestError(f"invalid version {version!r} (expected MAJOR.MINOR.PATCH)")
    m = Manifest(id=mid, name=name, version=version, path=path, trust=trust, warnings=warnings)
    m.description = _str(doc, "description", 300)
    m.roadmap = _str(doc, "roadmap", 80)
    m.min_platform = _str(doc, "min_platform", 32, default="0.0.0")
    if version_tuple(m.min_platform) is None:
        raise ManifestError("invalid min_platform")
    for key in ("enabled", "single_instance"):
        if key in doc:
            if not isinstance(doc[key], bool):
                raise ManifestError(f"'{key}' must be true or false")
            setattr(m, key, doc[key])
    if "order" in doc:
        if not isinstance(doc["order"], int) or isinstance(doc["order"], bool) or not 0 <= doc["order"] <= 100000:
            raise ManifestError("'order' must be an integer 0..100000")
        m.order = doc["order"]
    m.min_role = _str(doc, "min_role", 16, default="public")
    if m.min_role not in ROLES:
        raise ManifestError(f"invalid min_role {m.min_role!r}")
    m.status = _str(doc, "status", 16, default="available")
    if m.status not in ("available", "planned"):
        raise ManifestError(f"invalid status {m.status!r} (available | planned)")
    manifest_dir = path.parent if path else Path("/nonexistent")
    m.icon = _icon(doc.get("icon"), manifest_dir, warnings)

    launch = doc.get("launch")
    if launch is not None and not isinstance(launch, dict):
        raise ManifestError("[launch] must be a table")
    launch = launch or {}
    unknown = set(launch) - LAUNCH_KEYS
    if unknown:
        raise ManifestError(f"unknown [launch] key(s): {', '.join(sorted(unknown))}")
    if m.status == "planned":
        if launch:
            raise ManifestError("a planned app must not have a [launch] table")
    else:
        has_exec, has_builtin = "exec" in launch, "builtin" in launch
        if not has_exec and not has_builtin:
            raise ManifestError("[launch] needs 'exec' (or, in system manifests, 'builtin')")
        if has_builtin:
            if launch["builtin"] not in BUILTINS:
                raise ManifestError(f"unknown builtin {launch['builtin']!r}")
            if trust == "user":
                raise ManifestError("builtin handlers are reserved for system manifests")
            m.builtin = launch["builtin"]
            if has_exec and m.builtin not in EXEC_FALLBACK_BUILTINS:
                raise ManifestError(f"builtin {m.builtin!r} does not take 'exec'")
        if has_exec:
            m.exec = _argv(launch["exec"], "launch.exec")
        alts = launch.get("exec_alternatives", [])
        if not isinstance(alts, list) or len(alts) > 8:
            raise ManifestError("'launch.exec_alternatives' must be a list of argv lists (at most 8)")
        m.exec_alternatives = [_argv(a, "launch.exec_alternatives") for a in alts]
        m.on_reactivate = launch.get("on_reactivate", "notify")
        if m.on_reactivate not in ("notify", "relaunch"):
            raise ManifestError("'launch.on_reactivate' must be 'notify' or 'relaunch'")
        m.labels = _labels(launch.get("labels", {}), m.candidates())

    if "readiness" in doc:
        m.readiness = _str(doc, "readiness", 32)
        if m.readiness not in READINESS_PROBES:
            raise ManifestError(f"unknown readiness probe {m.readiness!r} ({', '.join(READINESS_PROBES)})")
    m.status_note = _str(doc, "status_note", 60)
    m.actions = _actions(doc.get("actions", []))
    if m.status == "planned" and m.actions:
        raise ManifestError("a planned app must not have actions")

    req = doc.get("requires", {})
    if not isinstance(req, dict):
        raise ManifestError("[requires] must be a table")
    unknown = set(req) - REQUIRES_KEYS
    if unknown:
        raise ManifestError(f"unknown [requires] key(s): {', '.join(sorted(unknown))}")
    m.hardware = _strlist(req.get("hardware", []), "requires.hardware")
    m.core_capabilities = _strlist(req.get("core_capabilities", []), "requires.core_capabilities")
    m.debian = _strlist(req.get("debian", []), "requires.debian")
    if "core_min_version" in req:
        if not isinstance(req["core_min_version"], str) or version_tuple(req["core_min_version"]) is None:
            raise ManifestError("invalid requires.core_min_version")
        m.core_min_version = req["core_min_version"]
    return m


def load_file(path: Path, trust: str) -> Manifest:
    import os
    import stat as st

    lst = os.lstat(path)
    if st.S_ISLNK(lst.st_mode):
        raise ManifestError("symlinked manifests are not accepted")
    if not st.S_ISREG(lst.st_mode):
        raise ManifestError("not a regular file")
    if lst.st_size > MAX_FILE_BYTES:
        raise ManifestError(f"file larger than {MAX_FILE_BYTES} bytes")
    if lst.st_mode & st.S_IWOTH:
        raise ManifestError("manifest file is world-writable")
    if trust == "user" and lst.st_uid != os.getuid():
        raise ManifestError("user manifest not owned by the current user")
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise ManifestError("not valid UTF-8") from None
    return parse_text(text, path, trust)
