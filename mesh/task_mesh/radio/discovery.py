# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""USB serial discovery for Meshtastic radios.

We never call SerialInterface(devPath=None): the library's auto-detection can sys.exit() with more
than one port and hides CP2102-based boards whenever an Espressif device is present.
"""

from __future__ import annotations

import errno
import grp
import logging
import os
import re
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

from task_mesh.core.errors import ErrorCode
from task_mesh.domain.models import Classification, PortCandidate
from task_mesh.radio import usb_ids

log = logging.getLogger(__name__)
_TTY_RE = re.compile(r"^/dev/tty(USB|ACM)\d+$")


def _default_comports() -> list[Any]:
    import serial.tools.list_ports  # pyserial; reads sysfs, no subprocess

    return list(serial.tools.list_ports.comports())


def _symlink_map(directory: Path) -> dict[str, str]:
    """realpath -> symlink path, for /dev/serial/by-id or by-path. Missing dir -> {}."""
    out: dict[str, str] = {}
    try:
        entries = sorted(directory.iterdir())
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return out
    for entry in entries:
        try:
            real = os.path.realpath(entry)
        except OSError:
            continue
        out.setdefault(real, str(entry))
    return out


def classify(vid: Optional[int], pid: Optional[int], excluded: Iterable[str] = (), paths: Iterable[str] = ()) -> Classification:
    excl = set(excluded)
    if usb_ids.is_never(vid) or any(p in excl for p in paths if p):
        return Classification.NEVER
    if usb_ids.is_likely(vid, pid):
        return Classification.LIKELY
    return Classification.POSSIBLE


def enumerate_ports(
    comports: Optional[Callable[[], Sequence[Any]]] = None,
    serial_dir: Path = Path("/dev/serial"),
    excluded_paths: Iterable[str] = (),
) -> list[PortCandidate]:
    """Return USB tty candidates (ttyUSB*/ttyACM* with a VID), NEVER ones included but marked."""
    try:
        ports = (comports or _default_comports)()
    except Exception as exc:  # noqa: BLE001 - enumeration must never crash the app
        log.warning("port enumeration failed: %s", exc, extra={"event": "radio.discovery_error"})
        return []
    by_id = _symlink_map(serial_dir / "by-id")
    by_path = _symlink_map(serial_dir / "by-path")
    excluded = list(excluded_paths)
    cands: list[PortCandidate] = []
    for p in ports:
        dev = getattr(p, "device", None)
        vid = getattr(p, "vid", None)
        if not dev or vid is None or not _TTY_RE.match(dev):
            continue
        real = os.path.realpath(dev)
        bid, bpath = by_id.get(real) or by_id.get(dev), by_path.get(real) or by_path.get(dev)
        pid = getattr(p, "pid", None)
        cands.append(
            PortCandidate(
                device=dev,
                by_id=bid,
                by_path=bpath,
                vid=vid,
                pid=pid,
                serial_number=getattr(p, "serial_number", None) or None,
                manufacturer=getattr(p, "manufacturer", None) or None,
                product=getattr(p, "product", None) or None,
                classification=classify(vid, pid, excluded, (dev, bid, bpath)),
            )
        )
    # by-id is only trustworthy when (vid, pid, serial) is unique: two CP2102 boards usually both
    # report serial "0001" and udev then points ONE by-id symlink at whichever enumerated last.
    keyed: dict[tuple, int] = {}
    for c in cands:
        key = (c.vid, c.pid, c.serial_number)
        keyed[key] = keyed.get(key, 0) + 1
    result = []
    for c in sorted(cands, key=lambda c: c.device):
        ambiguous = keyed[(c.vid, c.pid, c.serial_number)] > 1
        if c.by_id and not ambiguous:
            open_path = c.by_id
        elif c.by_path:
            open_path = c.by_path
        else:
            open_path = c.device
        result.append(replace(c, open_path=open_path, ambiguous_by_id=ambiguous))
    return result


class ChoiceKind(str, Enum):
    AUTO = "auto"
    SELECT = "select"
    NONE = "none"


@dataclass(frozen=True)
class Choice:
    kind: ChoiceKind
    candidate: Optional[PortCandidate]
    candidates: tuple[PortCandidate, ...]
    why: str


def _matches(c: PortCandidate, ident: Optional[dict]) -> bool:
    if not ident:
        return False
    if ident.get("by_id") and c.by_id == ident.get("by_id") and not c.ambiguous_by_id:
        return True
    if ident.get("by_id") and c.by_id and c.by_id != ident.get("by_id") and not c.ambiguous_by_id:
        return False  # a different, trustworthy by-id is a different device
    same_usb = (
        ident.get("vid") == c.vid and ident.get("pid") == c.pid and ident.get("serial") == c.serial_number
        and c.vid is not None
    )
    if same_usb and not c.ambiguous_by_id:
        return True
    return bool(same_usb and ident.get("by_path") and ident.get("by_path") == c.by_path)


def choose_candidate(
    candidates: Sequence[PortCandidate],
    pinned: Optional[dict] = None,
    last_success: Optional[dict] = None,
) -> Choice:
    usable = tuple(c for c in candidates if c.classification is not Classification.NEVER)
    if not usable:
        return Choice(ChoiceKind.NONE, None, usable, "no usable USB serial device")
    for c in usable:
        if _matches(c, pinned):
            return Choice(ChoiceKind.AUTO, c, usable, "pinned device")
    likely = [c for c in usable if c.classification is Classification.LIKELY]
    for c in likely:
        if _matches(c, last_success):
            return Choice(ChoiceKind.AUTO, c, usable, "last successfully connected device")
    if len(likely) == 1:
        return Choice(ChoiceKind.AUTO, likely[0], usable, "single likely Meshtastic device")
    if len(likely) > 1:
        return Choice(ChoiceKind.SELECT, None, usable, "several likely devices; user must choose")
    return Choice(ChoiceKind.SELECT, None, usable, "only unrecognised USB serial devices; user must choose")


@dataclass(frozen=True)
class Preflight:
    ok: bool
    code: Optional[ErrorCode] = None
    message: str = ""


def preflight(path: str) -> Preflight:
    """Cheap, non-blocking checks before opening a port."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return Preflight(False, ErrorCode.NO_DEVICE, f"{path} does not exist")
    except PermissionError as exc:
        return Preflight(False, ErrorCode.PERMISSION_DENIED, str(exc))
    except OSError as exc:
        return Preflight(False, ErrorCode.SERIAL_ERROR, str(exc))
    if os.access(path, os.R_OK | os.W_OK):
        return Preflight(True)
    try:
        group = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        group = str(st.st_gid)
    member = st.st_gid in os.getgroups()
    hint = (
        f"you are in group '{group}' but this session may predate it; log out and back in"
        if member
        else f"device is owned by group '{group}' and your user is not a member"
    )
    return Preflight(False, ErrorCode.PERMISSION_DENIED, f"cannot open {path}: {hint}")


def is_busy_error(exc: BaseException) -> bool:
    text = str(exc)
    return "exclusively lock" in text or getattr(exc, "errno", None) in (errno.EAGAIN, errno.EBUSY)
