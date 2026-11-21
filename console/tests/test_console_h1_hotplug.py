# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""H1: an RTL-SDR unplug seen by the real UdevEnumerator reaches the console.

On the Pi (2026-10-08) the console kept showing "14 connected, 0 disconnected"
after the SDR was unplugged because task-core never published the removal. The
console itself reacts to device.counts and device.* events; these tests pin that
end to end with the real task-core Core and the H1 live-monitor harness.
"""

from h1_live import LiveContext, LiveEnumerator, _fast, sdr_udev
from p2fixtures import SDR_ID


def _boot(p2env, devices):
    context = LiveContext(devices)
    enum = LiveEnumerator(context, **_fast(rescan_interval=0))
    core = p2env(devices=[], do_open=False)
    core.enumerator_factory = lambda: enum
    core.open()
    return core, context


def test_h1_console_public_counts_follow_sdr_unplug_and_replug(p2env, console):
    sdr = sdr_udev()
    core, context = _boot(p2env, [sdr])
    public = console(core.config.socket)
    counts = public.window.devices.public_counts
    # gps.primary (devices.json) is a disconnected placeholder; the SDR is connected
    public.qtbot.waitUntil(lambda: counts.text().startswith("1 connected \u00b7 1 disconnected"), timeout=3000)
    context.drop(sdr)
    context.push(sdr.at("unbind"), sdr.at("remove"))
    public.qtbot.waitUntil(lambda: counts.text().startswith("0 connected \u00b7 2 disconnected"), timeout=3000)
    context.add(sdr)
    context.push(sdr.at("add"), sdr.at("bind"))
    public.qtbot.waitUntil(lambda: counts.text().startswith("1 connected \u00b7 1 disconnected"), timeout=3000)


def test_h1_console_operator_device_row_follows_sdr_unplug(p2env, console):
    sdr = sdr_udev()
    core, context = _boot(p2env, [sdr])
    c = console(core.config.socket)
    c.sign_in("op")

    def sdr_connected():
        for device in (c.controller.devices or {}).get("devices", []):
            if device.get("id") == SDR_ID:
                return device.get("connected")
        return None

    c.qtbot.waitUntil(lambda: sdr_connected() is True, timeout=3000)
    context.drop(sdr)
    context.push(sdr.at("unbind"), sdr.at("remove"))
    c.qtbot.waitUntil(lambda: sdr_connected() is False, timeout=3000)
    context.add(sdr)
    context.push(sdr.at("add"))
    c.qtbot.waitUntil(lambda: sdr_connected() is True, timeout=3000)
