# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import hashlib
import logging
import threading
from dataclasses import dataclass

from task_core.errors import ApiError, PersistError
from task_core.persist import Store

logger = logging.getLogger("task_core")

LOGICAL = ("gps.primary", "mesh.primary", "sdr.primary", "radio.primary")
CLASSES = {"gps", "mesh", "sdr", "radio", "network", "storage", "unknown"}
SDR_IDS = {("0bda", "2838")}
CAPABILITY_NAMES = {
    "gps.position",
    "radio.rx",
    "radio.tx",
    "mesh.messaging",
    "mesh.position",
    "weather.products",
}


def is_real_serial(serial: str | None) -> bool:
    if serial is None:
        return False
    text = serial.strip()
    if not text:
        return False
    return any(ch != "0" for ch in text)


def make_id(key: str) -> str:
    return "dev_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def identity_for(raw: "RawDevice") -> tuple[str, bool]:
    """Return (identity key, stable). Devnode is never the key."""
    vid = raw.vid.lower() if raw.vid else None
    pid = raw.pid.lower() if raw.pid else None
    if raw.by_id:
        name = raw.by_id.rstrip("/").split("/")[-1]
        if name:
            return f"serial-by-id:{name}", True
    if vid and pid and is_real_serial(raw.serial) and raw.subsystem != "net":
        return f"usb:{vid}:{pid}:{raw.serial.strip()}", True
    if vid and pid and (vid, pid) in SDR_IDS and not is_real_serial(raw.serial):
        bus = raw.bus_path or "unknown"
        # Bus path changes when the dongle moves, so this key is not stable.
        return f"sdr:{vid}:{pid}:{bus}", False
    if raw.subsystem == "net" and raw.mac:
        return f"net:{raw.mac.strip().lower()}", True
    return f"usb-path:{raw.bus_path or 'unknown'}", False


@dataclass
class RawDevice:
    devnode: str | None = None
    by_id: str | None = None
    vid: str | None = None
    pid: str | None = None
    serial: str | None = None
    manufacturer: str | None = None
    product: str | None = None
    subsystem: str = "other"
    mac: str | None = None
    bus_path: str | None = None


@dataclass
class DeviceRecord:
    id: str
    identity_key: str
    devnode: str | None
    by_id: str | None
    vid: str | None
    pid: str | None
    serial: str | None
    manufacturer: str | None
    product: str | None
    subsystem: str
    identity_stable: bool
    class_name: str
    potential: list
    connected: bool
    logical: str | None
    alias: str | None

    def public(self) -> dict:
        return {
            "id": self.id,
            "devnode": self.devnode,
            "by_id": self.by_id,
            "vid": self.vid,
            "pid": self.pid,
            "serial": self.serial,
            "manufacturer": self.manufacturer,
            "product": self.product,
            "subsystem": self.subsystem,
            "identity_stable": self.identity_stable,
            "class": self.class_name,
            "potential": list(self.potential),
            "connected": self.connected,
            "logical": self.logical,
            "alias": self.alias,
        }


def load_rules(path) -> list:
    import yaml

    if path is None or not path.is_file():
        logger.warning("device rules missing; every device is unknown")
        return []
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.error("internal error source=rules")
        return []
    raw_rules = document.get("rules", [])
    if not isinstance(raw_rules, list):
        logger.error("internal error source=rules")
        return []
    rules = []
    for entry in raw_rules:
        if not isinstance(entry, dict):
            continue
        if "logical" in entry:
            logger.warning("rules cannot assign logical devices")
        class_name = entry.get("class", "unknown")
        if class_name not in CLASSES:
            logger.warning("ignored device rule")
            continue
        potential = []
        for name in entry.get("potential") or []:
            if name in CAPABILITY_NAMES:
                potential.append(name)
            else:
                logger.warning("ignored device rule potential")
        rules.append(
            {
                "vid": _lower_or_none(entry.get("vid")),
                "pid": _lower_or_none(entry.get("pid")),
                "subsystem": entry.get("subsystem"),
                "class": class_name,
                "potential": potential,
            }
        )
    return rules


def classify(raw: RawDevice, rules: list) -> tuple[str, list]:
    vid = raw.vid.lower() if raw.vid else None
    pid = raw.pid.lower() if raw.pid else None
    for rule in rules:
        if rule["vid"] is not None and rule["vid"] != vid:
            continue
        if rule["pid"] is not None and rule["pid"] != pid:
            continue
        if rule["subsystem"] is not None and rule["subsystem"] != raw.subsystem:
            continue
        return rule["class"], list(rule["potential"])
    return "unknown", []


class Manager:
    """Logical devices and assignments. Does not open device nodes."""

    def __init__(self, store: Store, rules: list, bus) -> None:
        self.store = store
        self.rules = rules
        self.bus = bus
        self._lock = threading.RLock()
        self.records: dict[str, DeviceRecord] = {}
        self._assignments, self.assignments_ok = store.load_assignments()
        self._last_counts = None
        self._install_placeholders()

    def _install_placeholders(self) -> None:
        for logical, entry in self._assignments.items():
            self.records[entry["device_id"]] = DeviceRecord(
                id=entry["device_id"],
                identity_key="",
                devnode=None,
                by_id=None,
                vid=None,
                pid=None,
                serial=None,
                manufacturer=None,
                product=None,
                subsystem="other",
                identity_stable=False,
                class_name="unknown",
                potential=[],
                connected=False,
                logical=logical,
                alias=entry.get("alias"),
            )

    def apply_enumerated(self, raws: list[RawDevice]) -> None:
        with self._lock:
            for raw in raws:
                self._upsert(raw, emit=True)
            self._publish_counts()

    def appear(self, raw: RawDevice) -> None:
        with self._lock:
            self._upsert(raw, emit=True)
            self._publish_counts()

    def disappear(self, raw: RawDevice, replaced: bool = False) -> None:
        """Mark a device disconnected and announce it once.

        `replaced` is set by the enumerator when a USB parent that was reported
        before its serial interface existed is now represented by that interface.
        Such a record is also dropped from the device list, unless an assignment
        refers to it. An assigned record is never deleted; it is only flagged,
        exactly like any other removal.
        """
        with self._lock:
            key, _stable = identity_for(raw)
            device_id = make_id(key)
            record = self.records.get(device_id)
            if record is None:
                return
            was_connected = record.connected
            if was_connected:
                record.connected = False
                record.devnode = None
            if replaced and record.logical is None and self._saved(device_id) == (None, None):
                del self.records[device_id]
            if not was_connected:
                self._publish_counts()
                return
            self.bus.publish(
                "device.disappeared",
                "devmgr",
                {"id": device_id, "logical": record.logical},
            )
            self._publish_counts()

    def change(self, raw: RawDevice) -> None:
        with self._lock:
            self._upsert(raw, emit=False)
            self._publish_counts()

    def counts(self) -> dict:
        """device.counts: over exactly the records device.list returns."""
        with self._lock:
            total = len(self.records)
            connected = sum(1 for record in self.records.values() if record.connected)
            return {"total": total, "connected": connected, "disconnected": total - connected}

    def _publish_counts(self) -> None:
        # v2-only topic (never in the v1 ring); published only when the counts change.
        counts = self.counts()
        if counts == self._last_counts:
            return
        self._last_counts = counts
        self.bus.publish("device.counts", "devmgr", dict(counts))

    def displacement(self, logical: str, device_id: str) -> list:
        """What a Phase 1 assign of device_id to logical would take away (section 5.10)."""
        with self._lock:
            lost = []
            for other in sorted(self.records.values(), key=lambda item: item.id):
                if other.id != device_id and other.logical == logical:
                    lost.append({"logical": logical, "device_id": other.id})
            record = self.records.get(device_id)
            if record is not None and record.logical is not None and record.logical != logical:
                lost.append({"logical": record.logical, "device_id": device_id})
            return lost

    def _upsert(self, raw: RawDevice, emit: bool) -> None:
        key, stable = identity_for(raw)
        device_id = make_id(key)
        class_name, potential = classify(raw, self.rules)
        current = self.records.get(device_id)
        if current is None:
            logical, alias = self._saved(device_id)
            record = DeviceRecord(
                id=device_id,
                identity_key=key,
                devnode=raw.devnode,
                by_id=raw.by_id,
                vid=_lower_or_none(raw.vid),
                pid=_lower_or_none(raw.pid),
                serial=raw.serial,
                manufacturer=raw.manufacturer,
                product=raw.product,
                subsystem=raw.subsystem,
                identity_stable=stable,
                class_name=class_name,
                potential=potential,
                connected=True,
                logical=logical,
                alias=alias,
            )
            self.records[device_id] = record
            if raw.serial:
                logger.info("device appeared id=%s serial=%s", device_id, raw.serial)
            else:
                logger.info("device appeared id=%s", device_id)
            if emit:
                self.bus.publish(
                    "device.appeared", "devmgr", {"id": device_id, "logical": logical}
                )
            return
        current.identity_key = key
        current.devnode = raw.devnode
        current.by_id = raw.by_id
        current.vid = _lower_or_none(raw.vid)
        current.pid = _lower_or_none(raw.pid)
        current.serial = raw.serial
        current.manufacturer = raw.manufacturer
        current.product = raw.product
        current.subsystem = raw.subsystem
        current.identity_stable = stable
        current.class_name = class_name
        current.potential = potential
        was_connected = current.connected
        current.connected = True
        saved_logical, saved_alias = self._saved(device_id)
        if current.logical is None and saved_logical is not None:
            current.logical = saved_logical
            current.alias = saved_alias
        if emit and not was_connected:
            self.bus.publish(
                "device.appeared",
                "devmgr",
                {"id": device_id, "logical": current.logical},
            )

    def _saved(self, device_id: str) -> tuple[str | None, str | None]:
        for logical, entry in self._assignments.items():
            if entry["device_id"] == device_id:
                return logical, entry.get("alias")
        return None, None

    def connected_logicals(self) -> set[str]:
        with self._lock:
            return {
                record.logical
                for record in self.records.values()
                if record.logical and record.connected
            }

    def list_public(self) -> dict:
        with self._lock:
            devices = [record.public() for record in self.records.values()]
            devices.sort(key=lambda item: item["id"])
            return {"devices": devices, "assignments": self._assignment_view()}

    def get_public(self, params: dict) -> dict:
        with self._lock:
            if params.get("id"):
                record = self.records.get(params["id"])
            elif params.get("logical"):
                logical = params["logical"]
                if logical not in LOGICAL:
                    raise ApiError("invalid-logical-device", "invalid logical device")
                record = self._by_logical(logical)
            else:
                raise ApiError("bad-request", "missing id")
            if record is None:
                raise ApiError("not-found", "unknown device")
            return {"device": record.public()}

    def assign(
        self, logical: str, device_id: str, alias: str | None, v2: bool = False, confirm_displace: bool = False
    ) -> dict:
        """Phase 1 assign. With v2=True, a displacement needs confirm_displace (section 5.10)."""
        if logical not in LOGICAL:
            raise ApiError("invalid-logical-device", "invalid logical device")
        with self._lock:
            record = self.records.get(device_id)
            if record is None:
                raise ApiError("unknown-device", "unknown device")
            displaced = self.displacement(logical, device_id) if v2 else []
            if displaced and not confirm_displace:
                raise ApiError("would-displace", _displace_message(displaced))
            snapshot = {
                key: (item.logical, item.alias) for key, item in self.records.items()
            }
            for other in self.records.values():
                if other.id != device_id and other.logical == logical:
                    other.logical = None
                    other.alias = None
            record.logical = logical
            record.alias = alias
            try:
                self._write()
            except PersistError:
                for key, (prev_logical, prev_alias) in snapshot.items():
                    self.records[key].logical = prev_logical
                    self.records[key].alias = prev_alias
                raise
            for lost in displaced:
                self.bus.publish(
                    "device.displaced",
                    "devmgr",
                    {
                        "logical": lost["logical"],
                        "id": lost["device_id"],
                        "by": {"logical": logical, "id": device_id},
                    },
                )
            self.bus.publish(
                "device.assigned",
                "devmgr",
                {"id": device_id, "logical": logical},
            )
            result = {"logical": logical, "device_id": device_id, "alias": alias}
            if v2:
                result["displaced"] = displaced
            return result

    def unassign(self, logical: str) -> dict:
        if logical not in LOGICAL:
            raise ApiError("invalid-logical-device", "invalid logical device")
        with self._lock:
            snapshot = {
                key: (item.logical, item.alias) for key, item in self.records.items()
            }
            for record in self.records.values():
                if record.logical == logical:
                    record.logical = None
                    record.alias = None
            try:
                self._write()
            except PersistError:
                for key, (prev_logical, prev_alias) in snapshot.items():
                    self.records[key].logical = prev_logical
                    self.records[key].alias = prev_alias
                raise
            self.bus.publish("device.unassigned", "devmgr", {"logical": logical})
            return {"logical": logical, "device_id": None}

    def _by_logical(self, logical: str) -> DeviceRecord | None:
        for record in self.records.values():
            if record.logical == logical:
                return record
        return None

    def _assignment_view(self) -> dict:
        view = {}
        for record in self.records.values():
            if record.logical:
                view[record.logical] = {
                    "device_id": record.id,
                    "alias": record.alias,
                    "connected": record.connected,
                }
        return view

    def _write(self) -> None:
        assignments = {}
        for record in self.records.values():
            if record.logical:
                assignments[record.logical] = {
                    "device_id": record.id,
                    "alias": record.alias,
                }
        self.store.save_assignments(assignments)
        self._assignments = assignments


def _displace_message(displaced: list) -> str:
    return "; ".join(f"{lost['logical']} is held by {lost['device_id']}" for lost in displaced)


def _lower_or_none(value):
    if value is None:
        return None
    return str(value).lower()
