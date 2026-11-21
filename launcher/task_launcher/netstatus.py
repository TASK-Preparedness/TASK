# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Read-only network indicator (02-launcher-ui.md section 10).

Source 1: NetworkManager over the system D-Bus (QtDBus), properties ``State``, ``Connectivity``,
``PrimaryConnectionType`` and ``ConnectivityCheckEnabled`` of ``/org/freedesktop/NetworkManager``.
The launcher only *reads* them; it never asks NetworkManager to run a connectivity check and never
contacts any external host. When NetworkManager's own checking is disabled, Connectivity is
``unknown`` and the footer says ``Internet: unknown``.

Source 2 (NetworkManager absent): /sys/class/net/*/operstate -> link up/down only; internet unknown.
Runs in a PollWorker thread (never on the GUI thread).
"""

import os
from dataclasses import dataclass

NM_SERVICE = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
NM_STATE = {0: "unknown", 10: "asleep", 20: "disconnected", 30: "disconnecting", 40: "connecting",
            50: "connected-local", 60: "connected-site", 70: "connected-global"}
NM_CONNECTIVITY = {0: "unknown", 1: "none", 2: "portal", 3: "limited", 4: "full"}
INTERNET_TEXT = {"full": "online", "limited": "limited", "portal": "captive portal", "none": "none",
                 "unknown": "unknown"}
TYPE_TEXT = {"802-11-wireless": "Wi-Fi", "802-3-ethernet": "Ethernet", "gsm": "Mobile", "cdma": "Mobile",
             "bluetooth": "Bluetooth", "vpn": "VPN", "wireguard": "WireGuard", "bridge": "Bridge", "bond": "Bond",
             "vlan": "VLAN"}


@dataclass
class NetStatus:
    network: str = "Network —"       # pill text
    internet: str = "unknown"        # footer 'Internet: <x>'
    kind: str = "unknown"            # wifi | wired | other | none | unknown (icon choice)
    up: bool = None                  # None = unknown
    source: str = "none"             # networkmanager | sysfs | none
    detail: str = ""


def from_nm(props: dict) -> NetStatus:
    state = NM_STATE.get(props.get("State"), "unknown")
    conn = NM_CONNECTIVITY.get(props.get("Connectivity"), "unknown")
    if props.get("ConnectivityCheckEnabled") is False:
        conn = "unknown"
    ptype = props.get("PrimaryConnectionType") or ""
    label = TYPE_TEXT.get(ptype, "Network")
    kind = "wifi" if ptype == "802-11-wireless" else "wired" if ptype == "802-3-ethernet" else "other"
    st = NetStatus(source="networkmanager", internet=INTERNET_TEXT[conn])
    if state.startswith("connected"):
        st.network, st.kind, st.up = f"{label} · connected", kind, True
        if state == "connected-local":
            st.detail = "local network only (NetworkManager: connected-local)"
    elif state in ("connecting",):
        st.network, st.kind, st.up = f"{label} · connecting…", kind, False
    elif state in ("disconnected", "asleep", "disconnecting"):
        st.network, st.kind, st.up = "No network", "none", False
    else:
        st.network, st.kind, st.up = "Network —", "unknown", None
    if props.get("ConnectivityCheckEnabled") is False:
        st.detail = (st.detail + "; " if st.detail else "") + "NetworkManager connectivity checking is off"
    return st


def from_sysfs(root: str = "/sys/class/net") -> NetStatus:
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return NetStatus()
    up_wifi = up_wired = False
    seen = False
    for name in names:
        if name == "lo":
            continue
        base = os.path.join(root, name)
        try:
            with open(os.path.join(base, "operstate")) as fh:
                state = fh.read().strip()
        except OSError:
            continue
        if not os.path.exists(os.path.join(base, "device")):
            continue  # virtual interfaces (bridges, veth, docker) are not a network link
        seen = True
        if state == "up":
            if os.path.isdir(os.path.join(base, "wireless")) or os.path.isdir(os.path.join(base, "phy80211")):
                up_wifi = True
            else:
                up_wired = True
    if up_wifi or up_wired:
        label = "Wi-Fi" if up_wifi else "Ethernet"
        return NetStatus(network=f"{label} · link up", kind="wifi" if up_wifi else "wired", up=True, source="sysfs",
                         detail="kernel link state only (NetworkManager not reachable)")
    if seen:
        return NetStatus(network="No network", kind="none", up=False, source="sysfs",
                         detail="kernel link state only (NetworkManager not reachable)")
    return NetStatus()


def read_nm_dbus(bus=None, timeout_ms: int = 2000):
    """Return the NM property dict, or None if NetworkManager is not reachable. Blocking call with a
    timeout; must run in a worker thread."""
    from PySide6.QtDBus import QDBus, QDBusConnection, QDBusMessage

    conn = bus or QDBusConnection.systemBus()
    if not conn.isConnected():
        return None
    props = {}
    for name in ("State", "Connectivity", "PrimaryConnectionType", "ConnectivityCheckEnabled"):
        msg = QDBusMessage.createMethodCall(NM_SERVICE, NM_PATH, "org.freedesktop.DBus.Properties", "Get")
        msg.setArguments([NM_SERVICE, name])
        reply = conn.call(msg, QDBus.CallMode.Block, timeout_ms)
        if reply.type() != QDBusMessage.MessageType.ReplyMessage or not reply.arguments():
            if name in ("State", "Connectivity"):
                return None
            continue
        value = reply.arguments()[0]
        if hasattr(value, "variant"):
            value = value.variant()
        props[name] = value
    return props


def collect(nm_reader=read_nm_dbus, sysfs_root="/sys/class/net") -> NetStatus:
    try:
        props = nm_reader()
    except Exception:
        props = None
    if props:
        return from_nm(props)
    return from_sysfs(sysfs_root)
