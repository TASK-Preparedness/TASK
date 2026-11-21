# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""XDG Desktop Entry discovery, visibility and Exec parsing (registry/desktop.py). TEST DATA only."""

import os
from pathlib import Path

import pytest

from conftest import make_exec, write_desktop
from task_launcher.registry import desktop as D


# ------------------------------------------------------------------ Exec parsing
@pytest.mark.parametrize("value,argv", [
    ("foo", ["foo"]),
    ("foo %U", ["foo"]),
    ("foo %f --x", ["foo", "--x"]),
    ('"/opt/My App/run" --flag', ["/opt/My App/run", "--flag"]),
    ('foo "a b" c', ["foo", "a b", "c"]),
    (r'foo "say \\"hi\\""', ["foo", 'say "hi"']),          # \\" in the file -> \" after unescape -> "
    (r'foo "\\$HOME"', ["foo", "$HOME"]),
    ("foo 100%%", ["foo", "100%"]),
    ("foo %c", ["foo", "Name"]),
    ("foo %i", ["foo", "--icon", "ic"]),
    ("foo %k", ["foo", "/x/app.desktop"]),
    ("foo  --double-space", ["foo", "--double-space"]),
    ("foo %d %D %n %N %v %m", ["foo"]),
    ("foo --file=%f", ["foo", "--file="]),
])
def test_parse_exec(value, argv):
    assert D.parse_exec(value, name="Name", icon="ic", desktop_path="/x/app.desktop") == argv


@pytest.mark.parametrize("value,message", [
    ("foo;rm -rf ~", "reserved character"),
    ("foo | bar", "reserved"),
    ("foo $HOME", "reserved"),
    ("foo `id`", "reserved"),
    ("foo > /tmp/x", "reserved"),
    ('foo "unterminated', "unterminated"),
    ('foo "%f"', "inside a quoted"),
    ("foo %z", "unknown field code"),
    ("foo --a=%F", "on its own"),
    ("foo %", "dangling"),
    ("%f", "no program"),
])
def test_parse_exec_rejects(value, message):
    with pytest.raises(D.ExecError, match=message):
        D.parse_exec(value)


def test_string_level_unescape_happens_first():
    # \s is a space at the string level; it then splits like a literal space
    assert D.parse_exec(r"foo\sbar") == ["foo", "bar"]


# ------------------------------------------------------------------ discovery
def test_application_dirs_order_and_flatpak(tmp_path, monkeypatch):
    env = {"HOME": str(tmp_path), "XDG_DATA_HOME": str(tmp_path / "dh"), "XDG_DATA_DIRS": "/a:/b:relative"}
    (tmp_path / "dh" / "flatpak" / "exports" / "share").mkdir(parents=True)
    dirs = D.application_dirs(env)
    assert dirs[:3] == [tmp_path / "dh" / "applications", Path("/a/applications"), Path("/b/applications")]
    assert tmp_path / "dh" / "flatpak" / "exports" / "share" / "applications" in dirs
    assert all(p.is_absolute() for p in dirs)
    env2 = {"HOME": str(tmp_path)}
    assert D.application_dirs(env2)[1:3] == [Path("/usr/local/share/applications"), Path("/usr/share/applications")]


def test_user_overrides_system_and_dedup(tmp_path):
    user, system = tmp_path / "u", tmp_path / "s"
    write_desktop(user, "editor.desktop", Name="My Editor", Exec="true")
    write_desktop(system, "editor.desktop", Name="Editor", Exec="true")
    write_desktop(system, "kde/konsole.desktop", Name="Konsole", Exec="true")
    found = D.scan([user, system], langs=[])
    assert found["editor.desktop"].name == "My Editor"
    assert found["editor.desktop"].shadowed == [system / "editor.desktop"]
    assert "kde-konsole.desktop" in found          # subdirectory -> '-' in the desktop-file ID


def test_user_hidden_masks_system_entry(tmp_path):
    user, system = tmp_path / "u", tmp_path / "s"
    write_desktop(user, "app.desktop", Name="App", Exec="true", Hidden="true")
    write_desktop(system, "app.desktop", Name="App", Exec="true")
    found = D.scan([user, system], langs=[])
    assert D.visibility_problem(found["app.desktop"], ["labwc"]).startswith("Hidden")
    assert D.offerable(found, ["labwc"]) == []
    assert D.offerable(found, ["labwc"], include_hidden=True) == []   # deleted stays deleted


@pytest.mark.parametrize("keys,desktops,reason", [
    ({"NoDisplay": "true"}, ["labwc"], "NoDisplay"),
    ({"OnlyShowIn": "GNOME;KDE;"}, ["labwc", "wlroots"], "OnlyShowIn"),
    ({"OnlyShowIn": "XFCE;wlroots;"}, ["labwc", "wlroots"], ""),
    ({"NotShowIn": "wlroots;"}, ["labwc", "wlroots"], "NotShowIn"),
    ({"NotShowIn": "GNOME;"}, ["labwc", "wlroots"], ""),
    ({"OnlyShowIn": "labwc;"}, [], "OnlyShowIn"),
    ({"Type": "Link", "URL": "https://x"}, ["labwc"], "Type is Link"),
    ({"TryExec": "/nonexistent/prog"}, ["labwc"], "TryExec"),
    ({"X-KDE-SubstituteUID": "true"}, ["labwc"], "administrative"),
])
def test_visibility(tmp_path, keys, desktops, reason):
    data = {"Name": "App", "Exec": "true"}
    data.update(keys)
    write_desktop(tmp_path, "app.desktop", **data)
    entry = D.scan([tmp_path], langs=[])["app.desktop"]
    problem = D.visibility_problem(entry, desktops)
    assert (problem.startswith(reason) or reason in problem) if reason else problem == ""


def test_current_desktop_is_colon_separated():
    assert D.current_desktops({"XDG_CURRENT_DESKTOP": "labwc:wlroots"}) == ["labwc", "wlroots"]
    assert D.current_desktops({}) == []


@pytest.mark.parametrize("exec_value", ["pkexec /usr/bin/synaptic", "env FOO=1 pkexec x", "gksu y", "sudo z"])
def test_admin_heuristic(tmp_path, exec_value):
    write_desktop(tmp_path, "adm.desktop", Name="Admin", Exec=exec_value)
    entry = D.scan([tmp_path], langs=[])["adm.desktop"]
    assert entry.admin is True
    assert D.offerable({"a": entry}, ["labwc"]) == []
    assert len(D.offerable({"a": entry}, ["labwc"], include_admin=True)) == 1


def test_localized_name(tmp_path):
    write_desktop(tmp_path, "app.desktop", **{"Name": "Files", "Name[de]": "Dateien", "Name[de_AT]": "Dateien AT",
                                               "Exec": "true"})
    assert D.scan([tmp_path], langs=D.locale_candidates("de_DE.UTF-8"))["app.desktop"].name == "Dateien"
    assert D.scan([tmp_path], langs=D.locale_candidates("de_AT.UTF-8"))["app.desktop"].name == "Dateien AT"
    assert D.scan([tmp_path], langs=D.locale_candidates("C.UTF-8"))["app.desktop"].name == "Files"


def test_scan_never_follows_or_modifies(tmp_path):
    p = write_desktop(tmp_path, "app.desktop", Name="App", Exec="true")
    before = (p.read_bytes(), p.stat().st_mtime_ns)
    D.scan([tmp_path], langs=[])
    assert (p.read_bytes(), p.stat().st_mtime_ns) == before


def test_bad_files_are_skipped(tmp_path):
    (tmp_path / "bin.desktop").write_bytes(b"\xff\xfe\x00junk")
    (tmp_path / "nogroup.desktop").write_text("Name=x\n")
    write_desktop(tmp_path, "ok.desktop", Name="OK", Exec="true")
    found = D.scan([tmp_path], langs=[])
    assert found["bin.desktop"].problem == "unreadable desktop file"
    assert found["nogroup.desktop"].problem == "no [Desktop Entry] group"
    assert [e.id for e, _ in D.offerable(found, [])] == ["ok.desktop"]


# ------------------------------------------------------------------ launch plans
def test_plan_resolves_path_and_refuses_relative(safe_dir, tmp_path):
    bindir = safe_dir / "bin"
    make_exec(bindir, "myapp")
    write_desktop(tmp_path, "a.desktop", Name="A", Exec="myapp --go %U")
    write_desktop(tmp_path, "b.desktop", Name="B", Exec="./myapp")
    write_desktop(tmp_path, "c.desktop", Name="C", Exec="notinstalled")
    found = D.scan([tmp_path], langs=[])
    plan = D.plan_launch(found["a.desktop"], path_env=f"relative:{bindir}")
    assert plan.argv == [str(bindir / "myapp"), "--go"]
    assert D.plan_launch(found["b.desktop"], path_env=str(bindir)).status == "invalid"
    c = D.plan_launch(found["c.desktop"], path_env=str(bindir))
    assert c.status == "missing" and "not found on PATH" in c.problem
    assert D.plan_launch(None).status == "missing"


def test_plan_terminal_and_path(safe_dir, tmp_path):
    bindir = safe_dir / "bin"
    make_exec(bindir, "htop")
    make_exec(bindir, "lxterminal")
    write_desktop(tmp_path, "t.desktop", Name="T", Exec="htop", Terminal="true", Path=str(safe_dir))
    entry = D.scan([tmp_path], langs=[])["t.desktop"]
    plan = D.plan_launch(entry, path_env=str(bindir))
    assert plan.argv == [str(bindir / "lxterminal"), "-e", str(bindir / "htop")]
    assert plan.cwd == str(safe_dir)
    os.unlink(bindir / "lxterminal")
    plan = D.plan_launch(entry, path_env=str(bindir))
    assert plan.argv is None and "no terminal emulator" in plan.problem


def test_plan_missing_workdir_and_tryexec(safe_dir, tmp_path):
    bindir = safe_dir / "bin"
    make_exec(bindir, "x")
    write_desktop(tmp_path, "p.desktop", Name="P", Exec=str(bindir / "x"), Path="/nonexistent/dir")
    write_desktop(tmp_path, "t.desktop", Name="T", Exec=str(bindir / "x"), TryExec="/nonexistent/x")
    found = D.scan([tmp_path], langs=[])
    assert "working directory" in D.plan_launch(found["p.desktop"]).problem
    assert D.plan_launch(found["t.desktop"]).status == "missing"


def test_dbus_activatable_without_exec(tmp_path, safe_dir):
    write_desktop(tmp_path, "org.example.App.desktop", Name="DBus", DBusActivatable="true")
    entry = D.scan([tmp_path], langs=[])["org.example.App.desktop"]
    assert entry.problem == ""
    plan = D.plan_launch(entry, gio_path="/nonexistent/gio")
    assert plan.argv is None and plan.status == "unavailable" and "gio" in plan.problem
    gio = make_exec(safe_dir / "bin", "gio")
    plan = D.plan_launch(entry, gio_path=str(gio))
    assert plan.argv == [str(gio), "launch", str(entry.path)]


def test_icon_file_validation(tmp_path):
    png = tmp_path / "i.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert D.icon_file_ok(str(png))
    assert not D.icon_file_ok("relative.png")
    assert not D.icon_file_ok(str(tmp_path / "missing.png"))
    (tmp_path / "x.sh").write_text("#!")
    assert not D.icon_file_ok(str(tmp_path / "x.sh"))
