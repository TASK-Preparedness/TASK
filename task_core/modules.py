# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from task_core.capabilities import ORDER
from task_core.devices import LOGICAL

logger = logging.getLogger("task_core")

_ID = re.compile(r"^[a-z][a-z0-9-]*$")
_VERSION = re.compile(r"^[0-9]+(\.[0-9]+)*$")
_ROLES = ("public", "operator", "administrator")


@dataclass
class Manifest:
    id: str
    name: str
    version: str
    summary: str
    requires: list
    capability_requires: list
    logical_devices: list
    permissions: dict
    systemd: list
    state: str
    reason: str | None = None
    path: str = ""
    loaded: bool = False
    extra: dict = field(default_factory=dict)

    def public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "summary": self.summary,
            "state": self.state,
            "reason": self.reason,
            "requires": list(self.requires),
            "capabilities": {"requires": list(self.capability_requires)},
            "logical_devices": list(self.logical_devices),
            "permissions": self.permissions,
            "systemd": list(self.systemd),
        }


def load_manifests(directory: Path, bus) -> list[Manifest]:
    manifests: list[Manifest] = []
    if not directory.is_dir():
        logger.warning("module directory missing")
        return manifests
    for path in sorted(directory.glob("*.yaml")):
        manifest = _read_one(path)
        manifests.append(manifest)
        if manifest.loaded:
            bus.publish("module.loaded", "modules", {"id": manifest.id})
        else:
            bus.publish(
                "module.rejected",
                "modules",
                {"id": manifest.id, "reason": manifest.reason},
            )
    _reject_cycles(manifests, bus)
    return manifests


def recompute_states(manifests: list[Manifest], capability_status: dict, bus, announce: bool) -> None:
    loaded = [item for item in manifests if item.loaded]
    by_id = {item.id: item for item in loaded}
    states = {item.id: item.state for item in loaded}
    for _ in range(len(loaded) + 1):
        changed = False
        for manifest in loaded:
            new_state = _state_for(manifest, by_id, states, capability_status)
            if states[manifest.id] != new_state:
                states[manifest.id] = new_state
                changed = True
        if not changed:
            break
    for manifest in loaded:
        new_state = states[manifest.id]
        if announce and new_state != manifest.state:
            manifest.state = new_state
            bus.publish(
                "module.state", "modules", {"id": manifest.id, "state": new_state}
            )
        else:
            manifest.state = new_state


def _state_for(manifest: Manifest, by_id: dict, states: dict, capability_status: dict) -> str:
    for dep in manifest.requires:
        other = by_id.get(dep)
        if other is None or not other.loaded:
            return "inactive"
        if states.get(dep) != "ready":
            return "inactive"
    for name in manifest.capability_requires:
        if capability_status.get(name) != "available":
            return "inactive"
    return "ready"


def _reject_cycles(manifests: list[Manifest], bus) -> None:
    loaded = [item for item in manifests if item.loaded]
    by_id = {item.id: item for item in loaded}
    visiting: set[str] = set()
    visited: set[str] = set()
    cyclic: set[str] = set()

    def walk(module_id: str, stack: list[str]) -> None:
        if module_id in visiting:
            cyclic.update(stack[stack.index(module_id) :])
            return
        if module_id in visited or module_id not in by_id:
            return
        visiting.add(module_id)
        stack.append(module_id)
        for dep in by_id[module_id].requires:
            if dep in by_id:
                walk(dep, stack)
        stack.pop()
        visiting.remove(module_id)
        visited.add(module_id)

    for manifest in loaded:
        walk(manifest.id, [])
    for module_id in cyclic:
        manifest = by_id[module_id]
        manifest.loaded = False
        manifest.state = "rejected"
        manifest.reason = "dependency cycle"
        bus.publish(
            "module.rejected",
            "modules",
            {"id": manifest.id, "reason": manifest.reason},
        )


def _read_one(path: Path) -> Manifest:
    stem = path.stem
    blank = Manifest(
        id=stem,
        name="",
        version="",
        summary="",
        requires=[],
        capability_requires=[],
        logical_devices=[],
        permissions={role: [] for role in _ROLES},
        systemd=[],
        state="rejected",
        reason="invalid manifest",
        path=str(path),
        loaded=False,
    )
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        blank.reason = "invalid yaml"
        return blank
    if not isinstance(document, dict):
        blank.reason = "invalid manifest"
        return blank
    if document.get("api") != 1:
        blank.reason = "unsupported api"
        if isinstance(document.get("id"), str):
            blank.id = document["id"]
        return blank
    try:
        manifest = _validate(document, stem, path)
    except ValueError as exc:
        blank.reason = str(exc)
        if isinstance(document.get("id"), str):
            blank.id = document["id"]
        return blank
    return manifest


def _validate(document: dict, stem: str, path: Path) -> Manifest:
    module_id = document.get("id")
    if not isinstance(module_id, str) or not _ID.match(module_id):
        raise ValueError("invalid id")
    if module_id != stem:
        raise ValueError("id does not match filename")
    name = document.get("name")
    summary = document.get("summary")
    version = document.get("version")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("invalid name")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("invalid summary")
    if not isinstance(version, str) or not _VERSION.match(version):
        raise ValueError("invalid version")
    requires = _string_list(document.get("requires", []), "requires")
    capabilities = document.get("capabilities", {})
    if not isinstance(capabilities, dict):
        raise ValueError("invalid capabilities")
    capability_requires = _string_list(capabilities.get("requires", []), "capabilities")
    for item in capability_requires:
        if item not in ORDER:
            raise ValueError("unknown capability")
    logical_devices = _string_list(document.get("logical_devices", []), "logical_devices")
    for item in logical_devices:
        if item not in LOGICAL:
            raise ValueError("invalid logical device")
    permissions = _permissions(document.get("permissions", {}))
    systemd = _string_list(document.get("systemd", []), "systemd")
    for granted in permissions.values():
        for item in granted:
            if str(item).startswith("medical.patients"):
                raise ValueError("patient permission is not a manifest grant")
    return Manifest(
        id=module_id,
        name=name,
        version=version,
        summary=summary,
        requires=requires,
        capability_requires=capability_requires,
        logical_devices=logical_devices,
        permissions=permissions,
        systemd=systemd,
        state="inactive",
        reason=None,
        path=str(path),
        loaded=True,
    )


def _string_list(value, label: str) -> list:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"invalid {label}")
    return list(value)


def _permissions(value) -> dict:
    if not isinstance(value, dict):
        raise ValueError("invalid permissions")
    cleaned = {}
    for role in _ROLES:
        granted = value.get(role, [])
        if not isinstance(granted, list) or not all(isinstance(item, str) for item in granted):
            raise ValueError("invalid permissions")
        cleaned[role] = list(granted)
    return cleaned
