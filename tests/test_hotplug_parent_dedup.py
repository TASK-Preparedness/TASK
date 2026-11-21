"""Hot-plug USB parent dedup (task-core 0.1.1).

PHASE-1.md section 2: "When that USB serial interface is present, its USB parent
is not also reported." On a live replug the kernel announces the usb_device before
its tty child. 0.1.0 created a record for that parent and, once the tty arrived,
only flagged it disconnected, so it stayed in device.list ("ghost"). Seen on the Pi
as dev_621b7d85c708289b = usb-path:platform-xhci-hcd.0-usb-0:1.

These tests drive the real UdevEnumerator.start / _dispatch -> _from_udev ->
apply_event -> Manager path with stand-in udev device objects, and read results
over the socket API. Fixtures use the IDs and fields from Joshua's Pi 5.
"""

import json
import os
import threading

from task_core.devices import make_id
from task_core.enumerator import UdevEnumerator, EnumState

from conftest import LineClient

UBLOX_TTY_ID = "dev_74a462923d20f21e"
UBLOX_GHOST_ID = "dev_621b7d85c708289b"
SDR_ID = "dev_ca4a208a9242de2c"
CP2102_TTY_ID = "dev_ccbc25d5a4210a5a"
CP2102_GHOST_ID = "dev_64dc233a6867c56d"
UBLOX_BY_ID = "/dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_7_-_GPS_GNSS_Receiver-if00"
CP2102_BY_ID = "/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0"
XHCI = "/sys/devices/platform/axi/1000120000.pcie"
PORTS = [
    ("platform-xhci-hcd.0-usb-0:1", f"{XHCI}/1f00200000.usb/xhci-hcd.0/usb1/1-1"),
    ("platform-xhci-hcd.0-usb-0:2", f"{XHCI}/1f00200000.usb/xhci-hcd.0/usb1/1-2"),
    ("platform-xhci-hcd.1-usb-0:1", f"{XHCI}/1f00300000.usb/xhci-hcd.1/usb3/3-1"),
    ("platform-xhci-hcd.1-usb-0:2", f"{XHCI}/1f00300000.usb/xhci-hcd.1/usb3/3-2"),
]


class Udev:
    """Just the pyudev.Device surface that task_core.enumerator reads."""

    def __init__(self, subsystem, sys_path, properties, device_type=None, device_node=None,
                 parent=None, attributes=None, action=None):
        self.subsystem = subsystem
        self.sys_path = sys_path
        self.sys_name = sys_path.rsplit("/", 1)[-1]
        self.properties = properties
        self.device_type = device_type
        self.device_node = device_node
        self._parent = parent
        self.attributes = attributes or {}
        self.action = action

    def find_parent(self, subsystem, device_type=None):
        parent = self._parent
        if parent is None or parent.subsystem != subsystem:
            return None
        if device_type is not None and parent.device_type not in (None, device_type):
            return None
        return parent

    def at(self, action):
        return Udev(self.subsystem, self.sys_path, self.properties, self.device_type,
                    self.device_node, self._parent, self.attributes, action)


def ublox(port=0):
    id_path, sys_path = PORTS[port]
    parent = Udev("usb", sys_path, {
        "ID_VENDOR_ID": "1546", "ID_MODEL_ID": "01a7",
        "ID_VENDOR": "u-blox", "ID_MODEL": "u-blox 7 GPS/GNSS Receiver",
        "ID_PATH": id_path,  # u-blox 7 has no USB iSerial: no ID_SERIAL_SHORT
    }, device_type="usb_device", device_node="/dev/bus/usb/001/002")
    tty = Udev("tty", f"{sys_path}/{sys_path.rsplit('/', 1)[-1]}:1.0/tty/ttyACM0", {
        "ID_BUS": "usb", "ID_VENDOR_ID": "1546", "ID_MODEL_ID": "01a7",
        "ID_VENDOR": "u-blox", "ID_MODEL": "u-blox 7 GPS/GNSS Receiver",
        "ID_USB_DRIVER": "cdc_acm", "ID_PATH": id_path + ":1.0",
        "DEVLINKS": f"{UBLOX_BY_ID} /dev/serial/by-path/{id_path}:1.0",
    }, device_node="/dev/ttyACM0", parent=parent)
    return parent, tty


def cp2102(port=1):
    id_path, sys_path = PORTS[port]
    parent = Udev("usb", sys_path, {
        "ID_VENDOR_ID": "10c4", "ID_MODEL_ID": "ea60", "ID_SERIAL_SHORT": "0001",
        "ID_VENDOR": "Silicon_Labs", "ID_MODEL": "CP2102_USB_to_UART_Bridge_Controller",
        "ID_PATH": id_path,
    }, device_type="usb_device", device_node="/dev/bus/usb/001/003")
    tty = Udev("tty", f"{sys_path}/{sys_path.rsplit('/', 1)[-1]}:1.0/ttyUSB0/tty/ttyUSB0", {
        "ID_BUS": "usb", "ID_VENDOR_ID": "10c4", "ID_MODEL_ID": "ea60", "ID_SERIAL_SHORT": "0001",
        "ID_VENDOR": "Silicon_Labs", "ID_MODEL": "CP2102_USB_to_UART_Bridge_Controller",
        "ID_USB_DRIVER": "cp210x", "ID_PATH": id_path + ":1.0",
        "DEVLINKS": f"{CP2102_BY_ID} /dev/serial/by-path/{id_path}:1.0-port0",
    }, device_node="/dev/ttyUSB0", parent=parent)
    return parent, tty


def rtlsdr():
    id_path, sys_path = PORTS[2]
    return Udev("usb", sys_path, {
        "ID_VENDOR_ID": "0bda", "ID_MODEL_ID": "2838", "ID_SERIAL_SHORT": "00000001",
        "ID_VENDOR": "RTLSDRBlog", "ID_MODEL": "Blog_V4", "ID_PATH": id_path,
    }, device_type="usb_device", device_node="/dev/bus/usb/003/002")


def noise():
    """Things the 0.1.0 tty fix must keep excluding, plus one network interface."""
    items = [Udev("tty", f"/sys/devices/virtual/tty/{name}", {}, device_node=f"/dev/{name}")
             for name in ("tty", "tty0", "tty1", "tty63", "console", "ptmx", "ttyprintk")]
    items.append(Udev("tty", "/sys/devices/platform/soc/107d001000.serial/tty/ttyAMA10", {},
                      device_node="/dev/ttyAMA10"))
    items.append(Udev("net", "/sys/devices/platform/axi/1000120000.pcie/1f00100000.ethernet/net/eth0",
                      {"ID_PATH": "platform-1f00100000.ethernet"},
                      attributes={"perm_address": "2c:cf:67:00:00:01"}))
    return items


class _Context:
    def __init__(self, devices):
        self.devices = devices

    def list_devices(self, subsystem):
        return [item for item in self.devices if item.subsystem == subsystem]


class _NoMonitor:
    class Monitor:
        @staticmethod
        def from_netlink(_context):
            raise OSError("no netlink in tests")


class PiEnumerator(UdevEnumerator):
    """The real UdevEnumerator (start, _dispatch) with pyudev replaced by stand-ins."""

    def __init__(self, devices):
        self._pyudev = _NoMonitor
        self._context = _Context(devices)
        self._stop = threading.Event()
        self._thread = None
        self._on_appear = None
        self._on_disappear = None
        self._on_change = None
        self._state = EnumState()

    def plug(self, parent, tty):
        # Kernel/udev order on a live plug: usb_device add, usb_device bind, then the tty.
        for event in (parent.at("add"), parent.at("bind"), tty.at("add")):
            self._dispatch(event)

    def unplug(self, parent, tty):
        for event in (tty.at("remove"), parent.at("unbind"), parent.at("remove")):
            self._dispatch(event)


def boot(env, devices, state_dir=None):
    enum = PiEnumerator(devices)
    core = env(enumerator_factory=lambda: enum, state_dir=state_dir)
    return core, enum, LineClient(core.config.socket)


def listing(client):
    return client.request("device.list")["result"]


def ids(client):
    return sorted(item["id"] for item in listing(client)["devices"])


def by_id(client, device_id):
    for item in listing(client)["devices"]:
        if item["id"] == device_id:
            return item
    return None


def ghosts(client):
    return [item for item in listing(client)["devices"] if item["subsystem"] == "usb"
            and item["vid"] in ("1546", "10c4")]


def assign_gps(client):
    response = client.request(
        "device.assign", {"logical": "gps.primary", "device_id": UBLOX_TTY_ID, "alias": "smoke"}
    )
    assert response["ok"] is True


# Byte-for-byte what 0.1.0 writes for Joshua's assignment (persist.py save_assignments).
DEVICES_JSON_0_1_0 = (
    json.dumps(
        {"v": 1, "assignments": {"gps.primary": {"device_id": UBLOX_TTY_ID, "alias": "smoke"}}},
        indent=2,
    )
    + "\n"
).encode("utf-8")


def test_fixture_ids_match_the_pi():
    assert make_id("usb-path:platform-xhci-hcd.0-usb-0:1") == UBLOX_GHOST_ID
    assert make_id("serial-by-id:" + UBLOX_BY_ID.rsplit("/", 1)[-1]) == UBLOX_TTY_ID
    assert make_id("usb:10c4:ea60:0001") == CP2102_GHOST_ID


def test_parent_announced_before_child_is_not_left_in_device_list(env):
    parent, tty = ublox()
    core, enum, client = boot(env, [parent, tty])
    assert ids(client) == [UBLOX_TTY_ID]
    enum.unplug(parent, tty)
    enum.plug(parent, tty)
    assert ids(client) == [UBLOX_TTY_ID]
    assert ghosts(client) == []
    missing = client.request("device.get", {"id": UBLOX_GHOST_ID})
    assert missing["ok"] is False and missing["error"]["code"] == "not-found"
    client.close()


def test_event_sequence_for_a_replug_is_unchanged(env):
    """The transient parent is still announced and withdrawn (balanced pair), as in 0.1.0."""
    parent, tty = ublox()
    core, enum, client = boot(env, [parent, tty])
    assign_gps(client)
    start = len(client.request("events.recent")["result"]["events"])
    enum.unplug(parent, tty)
    enum.plug(parent, tty)
    events = client.request("events.recent")["result"]["events"][start:]
    seen = [(e["topic"], e["data"].get("id"), e["data"].get("logical"), e["data"].get("status"))
            for e in events if e["topic"].startswith("device.") or e["topic"] == "capability.changed"]
    assert seen == [
        ("device.disappeared", UBLOX_TTY_ID, "gps.primary", None),
        ("capability.changed", None, None, "no-device"),
        ("device.appeared", UBLOX_GHOST_ID, None, None),
        ("device.disappeared", UBLOX_GHOST_ID, None, None),
        ("device.appeared", UBLOX_TTY_ID, "gps.primary", None),
        ("capability.changed", None, None, "no-provider"),
    ]
    client.close()


def test_unplug_replug_cycle_keeps_id_assignment_and_connected_state(env):
    parent, tty = ublox()
    core, enum, client = boot(env, [parent, tty])
    assign_gps(client)
    for _cycle in range(3):
        enum.unplug(parent, tty)
        record = by_id(client, UBLOX_TTY_ID)
        assert record["connected"] is False and record["devnode"] is None
        assert record["logical"] == "gps.primary" and record["alias"] == "smoke"
        assert listing(client)["assignments"]["gps.primary"]["connected"] is False
        enum.plug(parent, tty)
        record = by_id(client, UBLOX_TTY_ID)
        assert record["connected"] is True and record["devnode"] == "/dev/ttyACM0"
        assert record["identity_stable"] is True and record["logical"] == "gps.primary"
        assert listing(client)["assignments"]["gps.primary"] == {
            "device_id": UBLOX_TTY_ID, "alias": "smoke", "connected": True}
        assert ids(client) == [UBLOX_TTY_ID]
    client.close()


def test_twenty_replugs_on_the_same_port_do_not_accumulate(env):
    parent, tty = ublox()
    core, enum, client = boot(env, [parent, tty, rtlsdr()])
    assign_gps(client)
    before = ids(client)
    for _ in range(20):
        enum.unplug(parent, tty)
        enum.plug(parent, tty)
        assert ids(client) == before
    assert ghosts(client) == []
    assert len(core.devices.records) == len(before)
    client.close()


def test_replugs_across_four_ports_do_not_accumulate(env):
    parent, tty = ublox(0)
    core, enum, client = boot(env, [parent, tty])
    assign_gps(client)
    for round_ in range(2):
        for port in (1, 2, 3, 0):
            enum.unplug(parent, tty)
            parent, tty = ublox(port)
            enum.plug(parent, tty)
            assert ids(client) == [UBLOX_TTY_ID]
            record = by_id(client, UBLOX_TTY_ID)
            assert record["connected"] is True and record["logical"] == "gps.primary"
    assert ghosts(client) == []
    assert len(core.devices.records) == 1
    client.close()


def test_serial_bearing_parent_cp2102_is_handled_the_same_way(env):
    parent, tty = cp2102()
    core, enum, client = boot(env, [parent, tty])
    assert ids(client) == [CP2102_TTY_ID]
    for _ in range(5):
        enum.unplug(parent, tty)
        assert by_id(client, CP2102_TTY_ID)["connected"] is False
        enum.plug(parent, tty)
        assert ids(client) == [CP2102_TTY_ID]
    record = by_id(client, CP2102_TTY_ID)
    assert record["class"] == "unknown" and record["potential"] == [] and record["logical"] is None
    assert client.request("device.get", {"id": CP2102_GHOST_ID})["error"]["code"] == "not-found"
    client.close()


def test_assigned_parent_record_is_never_deleted(env, tmp_path):
    """If an administrator (under 0.1.0) assigned the ghost id, it stays: flag only."""
    state = tmp_path / "state"
    state.mkdir()
    original = (
        json.dumps({"v": 1, "assignments": {"gps.primary": {"device_id": UBLOX_GHOST_ID, "alias": "ghost"}}},
                   indent=2) + "\n"
    ).encode()
    (state / "devices.json").write_bytes(original)
    parent, tty = ublox()
    core, enum, client = boot(env, [parent, tty], state_dir=state)
    start = len(client.request("events.recent")["result"]["events"])
    for _ in range(3):
        enum.unplug(parent, tty)
        enum.plug(parent, tty)
        record = by_id(client, UBLOX_GHOST_ID)
        assert record is not None
        assert record["logical"] == "gps.primary" and record["alias"] == "ghost"
        assert record["connected"] is False
    events = client.request("events.recent")["result"]["events"][start:]
    assert ("device.disappeared", UBLOX_GHOST_ID, "gps.primary") in [
        (e["topic"], e["data"].get("id"), e["data"].get("logical")) for e in events]
    assert sorted(ids(client)) == sorted([UBLOX_GHOST_ID, UBLOX_TTY_ID])
    assert (state / "devices.json").read_bytes() == original
    client.close()


def test_parent_is_reported_again_if_its_tty_goes_away_but_the_device_stays(env):
    """Only while its serial interface is present is the parent hidden (PHASE-1.md section 2)."""
    parent, tty = ublox()
    core, enum, client = boot(env, [parent, tty])
    enum._dispatch(tty.at("remove"))          # e.g. cdc_acm unbound; USB device still attached
    enum._dispatch(parent.at("change"))
    record = by_id(client, UBLOX_GHOST_ID)
    assert record is not None and record["connected"] is True and record["subsystem"] == "usb"
    assert by_id(client, UBLOX_TTY_ID)["connected"] is False
    enum._dispatch(tty.at("add"))             # interface back: parent replaced again
    assert ids(client) == [UBLOX_TTY_ID]
    assert by_id(client, UBLOX_TTY_ID)["connected"] is True
    client.close()


def test_devices_json_from_0_1_0_loads_unchanged_and_resaves_byte_identical(env, tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    path = state / "devices.json"
    path.write_bytes(DEVICES_JSON_0_1_0)
    inode = os.stat(path).st_ino
    parent, tty = ublox()
    core, enum, client = boot(env, [parent, tty], state_dir=state)
    assert listing(client)["assignments"]["gps.primary"] == {
        "device_id": UBLOX_TTY_ID, "alias": "smoke", "connected": True}
    for _ in range(5):
        enum.unplug(parent, tty)
        enum.plug(parent, tty)
    assert path.read_bytes() == DEVICES_JSON_0_1_0
    assert os.stat(path).st_ino == inode  # hot-plug never rewrites the file
    assign_gps(client)                    # same assignment re-saved through the replace sequence
    assert path.read_bytes() == DEVICES_JSON_0_1_0
    assert core.devices.store.steps == ["write", "flush", "fsync-file", "rename", "fsync-dir"]
    client.close()


# Captured from task-core 0.1.0 (git tag v0.1.0) with the same stand-in devices.
COLD_BOOT_GOLDEN_0_1_0 = json.loads(
    r'''
{
    "capabilities": {
        "capabilities": [
            {
                "kind": "device-backed",
                "name": "gps.position",
                "status": "no-device"
            },
            {
                "kind": "device-backed",
                "name": "radio.rx",
                "status": "no-device"
            },
            {
                "kind": "device-backed",
                "name": "radio.tx",
                "status": "no-device"
            },
            {
                "kind": "device-backed",
                "name": "mesh.messaging",
                "status": "no-device"
            },
            {
                "kind": "device-backed",
                "name": "mesh.position",
                "status": "no-device"
            },
            {
                "kind": "provider-only",
                "name": "weather.products",
                "status": "no-provider"
            }
        ]
    },
    "devices": {
        "assignments": {},
        "devices": [
            {
                "alias": null,
                "by_id": "/dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_7_-_GPS_GNSS_Receiver-if00",
                "class": "gps",
                "connected": true,
                "devnode": "/dev/ttyACM0",
                "id": "dev_74a462923d20f21e",
                "identity_stable": true,
                "logical": null,
                "manufacturer": "u-blox",
                "pid": "01a7",
                "potential": [
                    "gps.position"
                ],
                "product": "u-blox 7 GPS/GNSS Receiver",
                "serial": null,
                "subsystem": "usb-serial",
                "vid": "1546"
            },
            {
                "alias": null,
                "by_id": null,
                "class": "network",
                "connected": true,
                "devnode": null,
                "id": "dev_792fea216fed9e95",
                "identity_stable": true,
                "logical": null,
                "manufacturer": null,
                "pid": null,
                "potential": [],
                "product": null,
                "serial": null,
                "subsystem": "net",
                "vid": null
            },
            {
                "alias": null,
                "by_id": null,
                "class": "sdr",
                "connected": true,
                "devnode": "/dev/bus/usb/003/002",
                "id": "dev_ca4a208a9242de2c",
                "identity_stable": true,
                "logical": null,
                "manufacturer": "RTLSDRBlog",
                "pid": "2838",
                "potential": [
                    "radio.rx"
                ],
                "product": "Blog_V4",
                "serial": "00000001",
                "subsystem": "usb",
                "vid": "0bda"
            },
            {
                "alias": null,
                "by_id": "/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0",
                "class": "unknown",
                "connected": true,
                "devnode": "/dev/ttyUSB0",
                "id": "dev_ccbc25d5a4210a5a",
                "identity_stable": true,
                "logical": null,
                "manufacturer": "Silicon_Labs",
                "pid": "ea60",
                "potential": [],
                "product": "CP2102_USB_to_UART_Bridge_Controller",
                "serial": "0001",
                "subsystem": "usb-serial",
                "vid": "10c4"
            }
        ]
    },
    "modules": {
        "gps": "inactive",
        "medical": "ready",
        "mesh": "inactive",
        "radio": "inactive",
        "sdr": "inactive",
        "system": "ready",
        "weather": "inactive"
    }
}
'''
)


def test_cold_boot_matches_0_1_0_golden(env):
    pu, tu = ublox(0)
    pc, tc = cp2102(1)
    devices = noise() + [pu, tu, pc, tc, rtlsdr()]
    core, enum, client = boot(env, devices)
    observed = {
        "devices": listing(client),
        "capabilities": client.request("capability.list")["result"],
        "modules": {m["id"]: m["state"] for m in client.request("module.list")["result"]["modules"]},
    }
    assert observed == COLD_BOOT_GOLDEN_0_1_0
    client.close()
