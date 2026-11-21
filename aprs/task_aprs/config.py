# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""User configuration under ~/.config/task-aprs (0700 dir, 0600 files, atomic writes).

amateur.toml and gmrs.toml are separate files with separate attestations; radios.d/<id>.toml holds one
radio profile each, tagged with its service. Amateur and GMRS settings can never be used for each other.
Nothing here is ever written under /etc or touches Direwolf's configuration."""

import os
import re
import tomllib
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from task_comms import paths
from task_comms.txpolicy import AmateurConfig, GmrsConfig

MODULE = "task-aprs"
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
SERVICES = ("amateur", "gmrs")


def config_root() -> Path:
    return paths.config_dir(MODULE)


def _toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    s = str(v)
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def write_toml(path: Path, data: dict):
    paths.private_dir(path.parent)
    lines = ["# written by task-aprs; edit in the app"]
    for k, v in data.items():
        if v is None:
            continue
        lines.append(f"{k} = {_toml_value(v)}")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_toml(path: Path) -> dict:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _build(cls, data: dict):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


def load_amateur(root: Path = None) -> AmateurConfig:
    d = read_toml((root or config_root()) / "amateur.toml")
    if d.get("service", "amateur") != "amateur":
        return AmateurConfig()
    return _build(AmateurConfig, d)


def save_amateur(cfg: AmateurConfig, root: Path = None):
    write_toml((root or config_root()) / "amateur.toml", {"service": "amateur", **asdict(cfg)})


def load_gmrs(root: Path = None) -> GmrsConfig:
    d = read_toml((root or config_root()) / "gmrs.toml")
    if d.get("service", "gmrs") != "gmrs":
        return GmrsConfig()
    return _build(GmrsConfig, d)


def save_gmrs(cfg: GmrsConfig, root: Path = None):
    write_toml((root or config_root()) / "gmrs.toml", {"service": "gmrs", **asdict(cfg)})


@dataclass
class RadioProfile:
    id: str
    service: str                  # amateur | gmrs
    name: str = ""
    make: str = ""
    model: str = ""
    # amateur (through Direwolf)
    channel: int = 0
    interface: str = ""           # e.g. "DigiRig (from Direwolf PTT/ADEVICE; not opened)"
    power_note: str = ""
    # gmrs (radio-integrated data only)
    fcc_id: str = ""
    driver: str = ""              # gmrs driver id, e.g. "simulated"
    handheld: bool = False        # operator-recorded from the FCC grant
    integral_antenna: bool = False
    builtin_data: bool = False
    identified_by: str = ""
    identified_date: str = ""
    verified: bool = False        # set only by the operator after the hardware acceptance test
    verified_date: str = ""

    def validate(self):
        if not _ID.match(self.id):
            raise ValueError("profile id: lowercase letters, digits and '-' only")
        if self.service not in SERVICES:
            raise ValueError("service must be amateur or gmrs")
        if self.service == "amateur" and self.driver:
            raise ValueError("an amateur profile cannot have a GMRS driver")
        if self.service == "gmrs" and self.interface:
            raise ValueError("a GMRS profile cannot use a Direwolf/sound-card interface (§95.339)")
        return self


def radios_dir(root: Path = None) -> Path:
    return (root or config_root()) / "radios.d"


def save_profile(p: RadioProfile, root: Path = None):
    p.validate()
    write_toml(radios_dir(root) / f"{p.id}.toml", asdict(p))


def load_profiles(service: str, root: Path = None):
    out = []
    d = radios_dir(root)
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.toml")):
        data = read_toml(f)
        if data.get("service") != service or data.get("id") != f.stem:
            continue
        try:
            out.append(_build(RadioProfile, data).validate())
        except (TypeError, ValueError):
            continue
    return out
