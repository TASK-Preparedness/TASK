# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""T27/T28: 0.3.0 tab set; service mode never autoconnects the GUI radio."""
from task_mesh.app import build_application
from task_mesh.hub.locks import instance_lock

TABS = ["All Messages", "Meshtastic", "MeshCore", "Devices", "Network Status"]


def _names(ctx):
    t = ctx.window.tabs
    return [t.tabText(i) for i in range(t.count())]


def test_T27_direct_mode_has_the_five_tabs(qtbot, xdg):
    ctx = build_application(env=xdg, discover=lambda: [], hotplug=None, console_log=False, hub_mode="direct")
    try:
        assert _names(ctx) == TABS
        assert ctx.window._hub[0].local is not None
    finally:
        ctx.shutdown()


def test_T28_service_running_means_gui_does_not_own_radios(qtbot, xdg):
    lock = instance_lock(xdg).acquire()
    try:
        calls = []
        ctx = build_application(env=xdg, discover=lambda: calls.append(1) or [], hotplug=None, console_log=False)
        try:
            assert _names(ctx) == TABS
            assert ctx.window._hub[0].local is None
            assert any("task-mesh-service is running" in w for w in ctx.warnings)
        finally:
            ctx.shutdown()
    finally:
        lock.release()


def test_T31_per_conversation_mute_from_gui(qtbot, xdg):
    from task_mesh.hub.model import HubMessage
    ctx = build_application(env=xdg, discover=lambda: [], hotplug=None, console_log=False, hub_mode="direct")
    try:
        access, tabs, _ = ctx.window._hub
        access.local.on_message(HubMessage(protocol="meshcore", device="d", key="k", direction="in", kind="channel",
                                           conversation="ch:0", sender="", sender_label="x", text="t", ts=1.0))
        p = tabs.mc_msgs
        p.refresh()
        p.convs.setCurrentRow(0)
        p.mute_btn.setChecked(True)
        assert "meshcore|ch:0" in access.local.notifier.settings.muted_conversations
        assert access.local.store.unread()["total"] == 1      # counts unaffected; locked → not marked read
    finally:
        ctx.shutdown()
