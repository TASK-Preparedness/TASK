"""udev selection: ordinary ttys are not USB serial devices."""

from task_core.devices import RawDevice
from task_core.enumerator import (
    EnumState,
    _from_udev,
    apply_event,
    choose_present,
    seed_state,
)


class FakeUdev:
    def __init__(
        self,
        subsystem,
        device_node=None,
        properties=None,
        device_type=None,
        parent=None,
        sys_path=None,
        action=None,
        attributes=None,
    ):
        self.subsystem = subsystem
        self.device_node = device_node
        self.properties = properties or {}
        self.device_type = device_type
        self._parent = parent
        self.sys_path = sys_path
        self.sys_name = sys_path
        self.action = action
        self.attributes = attributes or {}

    def find_parent(self, subsystem, device_type=None):
        parent = self._parent
        if parent is None or parent.subsystem != subsystem:
            return None
        if device_type is not None and parent.device_type not in (None, device_type):
            return None
        return parent


def _plain_tty(node):
    return FakeUdev("tty", device_node=node, sys_path=f"/sys/devices/virtual/tty/{node.rsplit('/', 1)[-1]}")


def _usb_parent(sys_path="/sys/devices/pci/usb1/1-1"):
    return FakeUdev(
        "usb",
        device_node="/dev/bus/usb/001/004",
        device_type="usb_device",
        sys_path=sys_path,
        properties={
            "ID_VENDOR_ID": "1546",
            "ID_MODEL_ID": "01a7",
            "ID_SERIAL_SHORT": "12345",
            "ID_VENDOR": "u-blox AG - www.u-blox.com",
            "ID_MODEL": "u-blox 7 - GPS/GNSS Receiver",
            "ID_PATH": "pci-usb-0:1",
        },
    )


def _usb_tty(node="/dev/ttyACM0", parent=None, **props):
    properties = {
        "ID_BUS": "usb",
        "ID_VENDOR_ID": "1546",
        "ID_MODEL_ID": "01a7",
        "ID_SERIAL_SHORT": "12345",
        "ID_VENDOR": "u-blox AG - www.u-blox.com",
        "ID_MODEL": "u-blox 7 - GPS/GNSS Receiver",
        "ID_PATH": "pci-usb-0:1:1.0",
        "DEVLINKS": "/dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_7_-_GPS_GNSS_Receiver-if00",
    }
    properties.update(props)
    return FakeUdev(
        "tty",
        device_node=node,
        properties=properties,
        parent=parent,
        sys_path=f"/sys/devices/pci/usb1/1-1:1.0/{node.rsplit('/', 1)[-1]}",
    )


def test_virtual_and_platform_ttys_are_not_usb_serial():
    nodes = ["/dev/tty", "/dev/console", "/dev/ptmx", "/dev/ttyprintk", "/dev/ttyAMA10"]
    nodes.extend(f"/dev/tty{number}" for number in range(64))
    for node in nodes:
        assert _from_udev(_plain_tty(node)) is None


def test_platform_uart_with_no_usb_parent_is_excluded():
    device = FakeUdev(
        "tty",
        device_node="/dev/ttyAMA10",
        properties={"ID_BUS": "platform", "DEVLINKS": "/dev/serial0"},
        sys_path="/sys/devices/platform/serial/ttyAMA10",
    )
    assert _from_udev(device) is None


def test_name_alone_does_not_exclude_a_real_usb_tty():
    device = _plain_tty("/dev/tty0")
    device.properties = {
        "ID_BUS": "usb",
        "ID_VENDOR_ID": "1546",
        "ID_MODEL_ID": "01a7",
        "DEVLINKS": "/dev/serial/by-id/usb-example-if00",
    }
    raw = _from_udev(device)
    assert raw is not None
    assert raw.subsystem == "usb-serial"
    assert raw.by_id == "/dev/serial/by-id/usb-example-if00"


def test_usb_serial_keeps_by_id_and_identity_inputs():
    parent = _usb_parent()
    raw = _from_udev(_usb_tty("/dev/ttyACM0", parent=parent))
    assert raw.subsystem == "usb-serial"
    assert raw.devnode == "/dev/ttyACM0"
    assert raw.by_id.endswith("u-blox_7_-_GPS_GNSS_Receiver-if00")
    assert raw.vid == "1546"
    assert raw.pid == "01a7"
    assert raw.serial == "12345"
    cp2102 = _usb_tty(
        "/dev/ttyUSB0",
        ID_VENDOR_ID="10c4",
        ID_MODEL_ID="ea60",
        ID_SERIAL_SHORT="0001",
        ID_USB_DRIVER="cp210x",
        DEVLINKS="/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0",
    )
    cp2102.properties.pop("ID_BUS")
    parsed = _from_udev(cp2102)
    assert parsed.subsystem == "usb-serial"
    assert parsed.devnode == "/dev/ttyUSB0"
    assert parsed.by_id.startswith("/dev/serial/by-id/usb-Silicon_Labs_")


def test_sysfs_parent_counts_as_usb_even_without_id_bus():
    parent = _usb_parent()
    device = FakeUdev(
        "tty",
        device_node="/dev/ttyACM0",
        properties={"DEVLINKS": ""},
        parent=parent,
        sys_path="/sys/devices/pci/usb1/1-1:1.0/ttyACM0",
    )
    raw = _from_udev(device)
    assert raw is not None
    assert raw.subsystem == "usb-serial"


def test_same_physical_serial_device_is_reported_once():
    parent_path = "/sys/devices/pci/usb1/1-1"
    parent = _usb_parent(parent_path)
    tty = _usb_tty("/dev/ttyACM0", parent=parent)
    rtl = FakeUdev(
        "usb",
        device_type="usb_device",
        sys_path="/sys/devices/pci/usb1/1-2",
        properties={
            "ID_VENDOR_ID": "0bda",
            "ID_MODEL_ID": "2838",
            "ID_SERIAL_SHORT": "00000001",
            "ID_PATH": "pci-usb-0:2",
        },
    )
    net = FakeUdev(
        "net",
        device_node=None,
        sys_path="/sys/devices/pci/net/wlan0",
        properties={"ID_PATH": "pci-wlan"},
        attributes={"perm_address": "b8:27:eb:00:00:01"},
    )
    scanned = [_scan(parent), _scan(tty), _scan(rtl), _scan(net)]
    chosen = [raw for raw, _sys, _parent in choose_present(scanned)]
    assert [item.devnode for item in chosen] == ["/dev/ttyACM0", None, None]
    assert chosen[0].subsystem == "usb-serial"
    assert chosen[0].by_id is not None
    assert chosen[1].subsystem == "usb"
    assert chosen[1].vid == "0bda"
    assert chosen[2].subsystem == "net"
    assert chosen[2].mac == "b8:27:eb:00:00:01"


def test_usb_parent_seen_before_tty_is_replaced_not_merged():
    parent_path = "/sys/devices/pci/usb1/1-1"
    parent = _from_udev(_usb_parent(parent_path))
    tty = _from_udev(_usb_tty())
    state = EnumState()
    first = apply_event(state, parent, parent_path, None, "add")
    assert [kind for kind, _item in first] == ["appear"]
    second = apply_event(state, tty, tty_sys(), parent_path, "add")
    assert [kind for kind, _item in second] == ["disappear", "appear"]
    assert second[0][1].subsystem == "usb"
    assert second[1][1].subsystem == "usb-serial"
    assert second[1][1].by_id == tty.by_id
    assert apply_event(state, parent, parent_path, None, "add") == []
    state_from_scan = seed_state(choose_present([
        (parent, parent_path, None),
        (tty, tty_sys(), parent_path),
    ]))
    assert parent_path in state_from_scan.serial_parents
    assert parent_path not in state_from_scan.emitted_usb


def _scan(device):
    from task_core.enumerator import _scan_item

    return _scan_item(device)


def tty_sys():
    return "/sys/devices/pci/usb1/1-1:1.0/ttyACM0"
