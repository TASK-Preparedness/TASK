# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Discovery and safe launching of installed desktop applications (freedesktop.org
Desktop Entry Specification 1.5).

* Discovery: $XDG_DATA_HOME/applications, then each $XDG_DATA_DIRS/applications (default
  /usr/local/share:/usr/share), plus the flatpak export directories if they exist and are not
  already listed. Desktop-file IDs are the path below ``applications/`` with "/" -> "-"; the first
  directory that provides an ID wins (user overrides system), so each ID appears once. A
  ``Hidden=true`` entry deletes the ID (also masking lower-precedence copies).
* Visibility: Type=Application only; NoDisplay=true, OnlyShowIn/NotShowIn against the
  colon-separated $XDG_CURRENT_DESKTOP (e.g. ``labwc:wlroots``), a failing TryExec, and
  administrative launchers (heuristic, see ADMIN_PROGRAMS) are not offered by default.
* Exec: parsed with the spec's own rules (string unescape, then double-quote quoting with the
  reserved-character rule, then field codes), never with a shell. The result is an argv list.

Nothing here modifies a .desktop file, installs or removes packages, or elevates privileges.
"""

import locale
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from task_launcher.registry.execcheck import check_executable, find_in_path

MAX_DESKTOP_BYTES = 256 * 1024
MAX_FILES_PER_DIR = 5000
RESERVED = set(" \t\n\"'\\><~|&;$*?#()`")
DEPRECATED_CODES = set("dDnNvm")
ADMIN_PROGRAMS = {"pkexec", "gksu", "gksudo", "kdesu", "kdesudo", "sudo", "su", "beesu", "lxqt-sudo",
                  "su-to-root", "lxsudo", "doas", "run0"}
ADMIN_KEYS = ("X-KDE-SubstituteUID", "X-KDE-RootOnly", "X-RequiresRoot", "X-GNOME-RequiresRoot")
# (program, how the command is passed). x-terminal-emulator must accept "-e command args"
# (Debian Policy 11.8.3); the rest are detected in this order.
TERMINALS = (
    ("x-terminal-emulator", ["-e"]),
    ("lxterminal", ["-e"]),
    ("foot", []),
    ("xfce4-terminal", ["-x"]),
    ("gnome-terminal", ["--"]),
    ("konsole", ["-e"]),
    ("alacritty", ["-e"]),
    ("kitty", []),
    ("xterm", ["-e"]),
)
ICON_EXTS = (".png", ".svg", ".xpm")
MAX_ICON_FILE = 2 * 1024 * 1024


class ExecError(ValueError):
    pass


# ---------------------------------------------------------------- file format

def unescape_string(value: str) -> str:
    """Spec 'Possible value types': \\s \\n \\t \\r \\\\ in string values."""
    out, i = [], 0
    table = {"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\"}
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value) and value[i + 1] in table:
            out.append(table[value[i + 1]])
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def split_list(value: str):
    """';'-separated list values; '\\;' is a literal semicolon."""
    items, cur, i = [], [], 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value) and value[i + 1] == ";":
            cur.append(";")
            i += 2
            continue
        if ch == ";":
            items.append(unescape_string("".join(cur)))
            cur = []
        else:
            cur.append(ch)
        i += 1
    if cur:
        items.append(unescape_string("".join(cur)))
    return [x for x in items if x != ""]


def parse_groups(text: str) -> dict:
    """{group: {key (with optional [locale]): raw value}}. First occurrence of a key wins."""
    groups, current = {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            groups.setdefault(current, {})
            continue
        if current is None or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z0-9-]+(\[[A-Za-z0-9_@.\-]+\])?", key):
            continue
        groups[current].setdefault(key, value.strip())
    return groups


def locale_candidates(lang: str = None):
    """'de_DE.UTF-8@euro' -> ['de_DE@euro', 'de_DE', 'de@euro', 'de'] (spec 'Localized values')."""
    if lang is None:
        lang = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
    if not lang or lang in ("C", "POSIX") or lang.startswith("C."):
        return []
    m = re.match(r"^([a-zA-Z]+)(?:_([a-zA-Z0-9]+))?(?:\.[^@]*)?(?:@(.*))?$", lang)
    if not m:
        return []
    ll, cc, mod = m.groups()
    out = []
    if cc and mod:
        out.append(f"{ll}_{cc}@{mod}")
    if cc:
        out.append(f"{ll}_{cc}")
    if mod:
        out.append(f"{ll}@{mod}")
    out.append(ll)
    return out


def localized(entry: dict, key: str, langs) -> str:
    for lc in langs:
        if f"{key}[{lc}]" in entry:
            return unescape_string(entry[f"{key}[{lc}]"])
    return unescape_string(entry.get(key, ""))


def is_true(value) -> bool:
    return isinstance(value, str) and value.strip() == "true"


# ---------------------------------------------------------------- Exec

def tokenize_exec(value: str):
    """Return a list of (text, quoted) tokens from an Exec value (after string unescaping)."""
    s = unescape_string(value)
    tokens, cur, quoted_tok, in_q, i, had = [], [], False, False, 0, False
    while i < len(s):
        ch = s[i]
        if in_q:
            if ch == "\\":
                if i + 1 < len(s) and s[i + 1] in '"`$\\':
                    cur.append(s[i + 1])
                    i += 2
                    continue
                raise ExecError("invalid backslash escape inside a quoted argument")
            if ch == '"':
                in_q = False
                i += 1
                continue
            cur.append(ch)
            i += 1
            continue
        if ch == " ":
            if had:
                tokens.append(("".join(cur), quoted_tok))
            cur, quoted_tok, had = [], False, False
            i += 1
            continue
        if ch == '"':
            in_q, quoted_tok, had = True, True, True
            i += 1
            continue
        if ch in RESERVED:
            raise ExecError(f"reserved character {ch!r} must be quoted in Exec")
        cur.append(ch)
        had = True
        i += 1
    if in_q:
        raise ExecError("unterminated double quote in Exec")
    if had:
        tokens.append(("".join(cur), quoted_tok))
    return tokens


def expand_field_codes(tokens, name: str = "", icon: str = "", desktop_path: str = ""):
    """Expand/remove field codes. No files/URLs are passed, so %f %F %u %U are removed."""
    argv = []
    for text, quoted in tokens:
        if not quoted and text in ("%f", "%F", "%u", "%U") or text in ("%d", "%D", "%n", "%N", "%v", "%m"):
            continue
        if not quoted and text == "%i":
            if icon:
                argv += ["--icon", icon]
            continue
        if not quoted and text == "%c":
            argv.append(name)
            continue
        if not quoted and text == "%k":
            if desktop_path:
                argv.append(desktop_path)
            continue
        out, i = [], 0
        while i < len(text):
            ch = text[i]
            if ch == "%":
                if i + 1 >= len(text):
                    raise ExecError("dangling '%' in Exec")
                code = text[i + 1]
                if code == "%":
                    out.append("%")
                elif quoted:
                    raise ExecError(f"field code %{code} inside a quoted argument")
                elif code in "fu" or code in DEPRECATED_CODES:
                    pass  # embedded single-file code without a file: removed
                elif code in "FUick":
                    raise ExecError(f"field code %{code} must be an argument on its own")
                else:
                    raise ExecError(f"unknown field code %{code}")
                i += 2
                continue
            out.append(ch)
            i += 1
        argv.append("".join(out))
    if not argv or not argv[0]:
        raise ExecError("Exec has no program")
    return argv


def parse_exec(value: str, name: str = "", icon: str = "", desktop_path: str = ""):
    return expand_field_codes(tokenize_exec(value), name, icon, desktop_path)


def find_terminal(path_env: str = None):
    for prog, flag in TERMINALS:
        found = find_in_path(prog, path_env)
        if found:
            return found, flag
    return None, None


# ---------------------------------------------------------------- entries

@dataclass
class DesktopEntry:
    id: str
    path: Path
    name: str = ""
    generic_name: str = ""
    comment: str = ""
    keywords: list = field(default_factory=list)
    icon: str = ""
    exec: str = ""
    try_exec: str = ""
    workdir: str = ""
    terminal: bool = False
    dbus_activatable: bool = False
    no_display: bool = False
    hidden: bool = False
    only_show_in: list = field(default_factory=list)
    not_show_in: list = field(default_factory=list)
    type: str = ""
    admin: bool = False
    problem: str = ""                 # why it cannot be offered / launched ('' = fine)
    shadowed: list = field(default_factory=list)  # lower-precedence files with the same ID

    def search_text(self) -> str:
        return " ".join([self.name, self.generic_name, self.comment, " ".join(self.keywords), self.id]).lower()


def application_dirs(env=None):
    env = os.environ if env is None else env
    home = env.get("HOME") or str(Path.home())
    data_home = env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    data_dirs = env.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    dirs = [data_home] + [d for d in data_dirs.split(":") if d]
    for extra in (os.path.join(data_home, "flatpak", "exports", "share"), "/var/lib/flatpak/exports/share"):
        if os.path.isdir(extra) and extra not in dirs:
            dirs.append(extra)
    out, seen = [], set()
    for d in dirs:
        if not os.path.isabs(d):
            continue
        p = Path(d) / "applications"
        if str(p) not in seen:
            seen.add(str(p))
            out.append(p)
    return out


def current_desktops(env=None):
    env = os.environ if env is None else env
    return [d for d in (env.get("XDG_CURRENT_DESKTOP") or "").split(":") if d]


def read_entry(path: Path, desktop_id: str, langs=None) -> DesktopEntry:
    entry = DesktopEntry(id=desktop_id, path=path)
    try:
        st = path.stat()
        if st.st_size > MAX_DESKTOP_BYTES:
            entry.problem = "desktop file too large"
            return entry
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        entry.problem = "unreadable desktop file"
        return entry
    groups = parse_groups(text)
    de = groups.get("Desktop Entry")
    if de is None:
        entry.problem = "no [Desktop Entry] group"
        return entry
    langs = locale_candidates() if langs is None else langs
    entry.type = de.get("Type", "")
    entry.name = localized(de, "Name", langs).strip()
    entry.generic_name = localized(de, "GenericName", langs).strip()
    entry.comment = localized(de, "Comment", langs).strip()
    kw = None
    for lc in langs:
        if f"Keywords[{lc}]" in de:
            kw = de[f"Keywords[{lc}]"]
            break
    entry.keywords = split_list(kw if kw is not None else de.get("Keywords", ""))
    entry.icon = localized(de, "Icon", langs).strip()
    entry.exec = de.get("Exec", "")
    entry.try_exec = unescape_string(de.get("TryExec", "")).strip()
    entry.workdir = unescape_string(de.get("Path", "")).strip()
    entry.terminal = is_true(de.get("Terminal"))
    entry.dbus_activatable = is_true(de.get("DBusActivatable"))
    entry.no_display = is_true(de.get("NoDisplay"))
    entry.hidden = is_true(de.get("Hidden"))
    entry.only_show_in = split_list(de.get("OnlyShowIn", ""))
    entry.not_show_in = split_list(de.get("NotShowIn", ""))
    entry.admin = any(is_true(de.get(k)) for k in ADMIN_KEYS)
    if entry.exec:
        try:
            argv = parse_exec(entry.exec, entry.name, entry.icon, str(path))
            prog = os.path.basename(argv[0])
            if prog in ADMIN_PROGRAMS:
                entry.admin = True
            elif prog == "env":
                # 'env VAR=x prog' -> look at the first non-assignment word
                rest = [a for a in argv[1:] if "=" not in a and not a.startswith("-")]
                if rest and os.path.basename(rest[0]) in ADMIN_PROGRAMS:
                    entry.admin = True
        except ExecError:
            pass
    if entry.type != "Application":
        entry.problem = f"Type is {entry.type or 'missing'}, not Application"
    elif not entry.name:
        entry.problem = "no Name"
    elif not entry.exec and not entry.dbus_activatable:
        entry.problem = "no Exec"
    return entry


def visibility_problem(entry: DesktopEntry, desktops) -> str:
    """'' if the entry should be offered in 'Add Application'; else the reason."""
    if entry.problem:
        return entry.problem
    if entry.hidden:
        return "Hidden=true (deleted)"
    if entry.no_display:
        return "NoDisplay=true"
    if entry.only_show_in and not any(d in entry.only_show_in for d in desktops):
        return f"OnlyShowIn={';'.join(entry.only_show_in)} (current desktop: {':'.join(desktops) or 'unset'})"
    if entry.not_show_in and any(d in entry.not_show_in for d in desktops):
        return f"NotShowIn={';'.join(entry.not_show_in)}"
    if entry.try_exec and not _try_exec_ok(entry.try_exec):
        return f"TryExec {entry.try_exec} not installed"
    if entry.admin:
        return "administrative launcher (asks for elevated rights)"
    return ""


def _try_exec_ok(value: str) -> bool:
    if value.startswith("/"):
        return os.path.isfile(value) and os.access(value, os.X_OK)
    return find_in_path(value) is not None


def scan(dirs=None, langs=None):
    """Return {desktop_id: DesktopEntry} with spec precedence (first directory wins)."""
    dirs = application_dirs() if dirs is None else dirs
    langs = locale_candidates() if langs is None else langs
    found = {}
    for base in dirs:
        base = Path(base)
        if not base.is_dir():
            continue
        count = 0
        for root, subdirs, files in os.walk(base, followlinks=False):
            subdirs.sort()
            for name in sorted(files):
                if not name.endswith(".desktop"):
                    continue
                count += 1
                if count > MAX_FILES_PER_DIR:
                    break
                path = Path(root) / name
                desktop_id = str(path.relative_to(base)).replace("/", "-")
                if desktop_id in found:
                    found[desktop_id].shadowed.append(path)
                    continue
                found[desktop_id] = read_entry(path, desktop_id, langs)
    return found


def offerable(entries: dict, desktops=None, include_admin=False, include_hidden=False):
    """Entries for the 'Add Application' list, sorted by name. Returns [(entry, reason)]."""
    desktops = current_desktops() if desktops is None else desktops
    out = []
    for entry in entries.values():
        reason = visibility_problem(entry, desktops)
        if reason == "":
            out.append((entry, ""))
        elif include_admin and entry.admin and not entry.problem and not entry.hidden and not entry.no_display:
            out.append((entry, reason))
        elif include_hidden and not entry.problem and not entry.hidden:
            out.append((entry, reason))
    out.sort(key=lambda pair: (pair[0].name.casefold(), pair[0].id))
    return out


# ---------------------------------------------------------------- launch plan

@dataclass
class LaunchPlan:
    argv: list = None
    cwd: str = None
    problem: str = ""
    status: str = "ok"   # ok | missing | unsafe | invalid | unavailable


def plan_launch(entry: DesktopEntry, path_env: str = None, gio_path: str = "/usr/bin/gio") -> LaunchPlan:
    """Build the argv for an entry (no files). Never a shell."""
    if entry is None:
        return LaunchPlan(problem="application is no longer installed (desktop file gone)", status="missing")
    if entry.problem:
        return LaunchPlan(problem=entry.problem, status="invalid")
    if entry.hidden:
        return LaunchPlan(problem="desktop entry is Hidden=true (removed)", status="missing")
    if entry.try_exec and not _try_exec_ok(entry.try_exec):
        return LaunchPlan(problem=f"not installed: TryExec {entry.try_exec} not found", status="missing")
    if not entry.exec:
        # DBusActivatable without Exec: only through gio (GLib) if present
        if entry.dbus_activatable and os.path.isfile(gio_path) and os.access(gio_path, os.X_OK):
            return LaunchPlan(argv=[gio_path, "launch", str(entry.path)])
        return LaunchPlan(problem="D-Bus activation only (no Exec) and gio is not installed", status="unavailable")
    try:
        argv = parse_exec(entry.exec, entry.name, entry.icon, str(entry.path))
    except ExecError as exc:
        return LaunchPlan(problem=f"invalid Exec: {exc}", status="invalid")
    prog = argv[0]
    if "/" not in prog:
        resolved = find_in_path(prog, path_env)
        if resolved is None:
            return LaunchPlan(problem=f"not installed: {prog} not found on PATH", status="missing")
        prog = resolved
    elif not prog.startswith("/"):
        return LaunchPlan(problem=f"invalid Exec: relative program path {prog!r}", status="invalid")
    status, reason = check_executable(prog)
    if status != "ok":
        return LaunchPlan(problem=reason, status="missing" if status == "missing" else status)
    argv[0] = prog
    cwd = None
    if entry.workdir:
        if not os.path.isabs(entry.workdir) or not os.path.isdir(entry.workdir):
            return LaunchPlan(problem=f"Path= working directory does not exist: {entry.workdir}", status="invalid")
        cwd = entry.workdir
    if entry.terminal:
        term, flag = find_terminal(path_env)
        if term is None:
            return LaunchPlan(problem="Terminal=true but no terminal emulator is installed "
                                      "(x-terminal-emulator, lxterminal, foot, ...)", status="unavailable")
        argv = [term] + flag + argv
    return LaunchPlan(argv=argv, cwd=cwd)


def icon_file_ok(path: str) -> bool:
    """Absolute Icon= paths: existing regular image file of a known type, bounded size."""
    try:
        p = Path(path)
        return (p.is_absolute() and p.suffix.lower() in ICON_EXTS and p.is_file()
                and p.stat().st_size <= MAX_ICON_FILE)
    except OSError:
        return False


def default_langs():
    try:
        return locale_candidates(locale.getlocale(locale.LC_MESSAGES)[0] or None)
    except (ValueError, AttributeError):
        return locale_candidates()
