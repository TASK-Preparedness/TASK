# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Manifest schema v1 (MANIFEST-SPEC.md), discovery precedence and the 12 shipped manifests."""

import os

import pytest

from task_launcher.registry.discovery import BUNDLED_APPS_DIR, discover
from task_launcher.registry.manifest import ManifestError, load_file, parse_text

REFERENCE_ORDER = ["Mesh Network", "Maps & GPS", "Radio / APRS", "SDR", "Library", "Mission Planner",
                   "Medical", "Weather", "Devices", "Files", "System", "App Manager"]
PLANNED = {"task.mission-planner"}

BASE = 'manifest_version = 1\nid = "pub.app"\nname = "App"\nversion = "1.0.0"\n'


def shipped():
    ms, problems = discover([(BUNDLED_APPS_DIR, "package")])
    return ms, problems


def test_twelve_shipped_manifests_in_reference_order():
    ms, problems = shipped()
    assert problems == []
    ordered = sorted(ms.values(), key=lambda m: m.order)
    assert [m.name for m in ordered] == REFERENCE_ORDER
    assert len(ms) == 12
    for m in ordered:
        assert m.warnings == [], (m.id, m.warnings)
        assert isinstance(m.icon, str) and m.icon != "shapes"


def test_planned_manifests_have_no_exec():
    ms, _ = shipped()
    planned = {i for i, m in ms.items() if m.status == "planned"}
    assert planned == PLANNED   # Phase 4A: only Mission Planner
    for i in planned:
        assert ms[i].exec is None and ms[i].builtin is None and ms[i].exec_alternatives == []


def test_devices_manifest_uses_verified_rain_console_command():
    ms, _ = shipped()
    d = ms["task.devices"]
    assert d.builtin == "devices"
    assert d.exec == ["/usr/local/bin/task-console"]
    assert d.exec_alternatives == [["/usr/bin/task-console"], ["/usr/local/bin/rain-console"]]  # 4C legacy fallback
    assert d.on_reactivate == "relaunch"
    assert d.core_min_version == "0.2.0"


def test_all_shipped_files_carry_spdx():
    for p in BUNDLED_APPS_DIR.glob("*.toml"):
        text = p.read_text()
        assert "SPDX-License-Identifier: GPL-3.0-or-later" in text
        assert "SPDX-FileCopyrightText: 2026 Joshua Sturtz" in text


@pytest.mark.parametrize("extra,message", [
    ('bogus = 1\n', "unknown key"),
    ('[launch]\nexec = ["relative/bin"]\n', "absolute"),
    ('[launch]\nbuiltin = "system"\n', "reserved for system manifests"),
    ('[launch]\n', "needs 'exec'"),
    ('status = "planned"\n[launch]\nexec = ["/bin/true"]\n', "planned app must not"),
    ('min_role = "root"\n[launch]\nexec = ["/bin/true"]\n', "invalid min_role"),
    ('order = -1\n[launch]\nexec = ["/bin/true"]\n', "order"),
    ('[launch]\nexec = ["/bin/true"]\non_reactivate = "kill"\n', "on_reactivate"),
    ('[launch]\nexec = ["/bin/true"]\n[requires]\nroot = true\n', "unknown [requires]"),
])
def test_validation_errors(extra, message):
    with pytest.raises(ManifestError, match=message.replace("[", r"\[")):
        parse_text(BASE + extra, trust="user")


@pytest.mark.parametrize("text,message", [
    ('manifest_version = 2\nid = "a.b"\nname = "x"\nversion = "1.0.0"\n', "manifest_version"),
    ('manifest_version = 1\nid = "Bad Id"\nname = "x"\nversion = "1.0.0"\n', "invalid id"),
    ('manifest_version = 1\nid = "a.b"\nversion = "1.0.0"\n', "name"),
    ('manifest_version = 1\nid = "a.b"\nname = "x"\nversion = "1.0"\n', "invalid version"),
    ('manifest_version = 1\nid = "a.b"\nname = "' + "x" * 41 + '"\nversion = "1.0.0"\n', "name"),
    ('manifest_version = 1\nid = ', "malformed TOML"),
])
def test_required_fields(text, message):
    with pytest.raises(ManifestError, match=message):
        parse_text(text)


def test_bad_icon_is_a_warning_with_fallback():
    m = parse_text(BASE + 'icon = "no-such-icon"\n[launch]\nexec = ["/bin/true"]\n')
    assert m.icon == "shapes" and "no bundled icon" in m.warnings[0]
    m = parse_text(BASE + 'icon = "/etc/passwd"\n[launch]\nexec = ["/bin/true"]\n')
    assert m.icon == "shapes" and m.warnings


def test_svg_icon_with_script_is_refused(tmp_path):
    (tmp_path / "evil.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>x</script></svg>')
    f = tmp_path / "a.toml"
    f.write_text(BASE + 'icon = "evil.svg"\n[launch]\nexec = ["/bin/true"]\n')
    m = load_file(f, "user")
    assert m.icon == "shapes" and "scripts" in m.warnings[0]


def test_load_file_refuses_symlink_world_writable_and_large(tmp_path):
    good = tmp_path / "good.toml"
    good.write_text(BASE + '[launch]\nexec = ["/bin/true"]\n')
    assert load_file(good, "user").id == "pub.app"
    link = tmp_path / "link.toml"
    link.symlink_to(good)
    with pytest.raises(ManifestError, match="symlink"):
        load_file(link, "user")
    good.chmod(0o666)
    with pytest.raises(ManifestError, match="world-writable"):
        load_file(good, "user")
    good.chmod(0o644)
    big = tmp_path / "big.toml"
    big.write_text(BASE + "#" + "x" * 70000 + "\n")
    with pytest.raises(ManifestError, match="larger"):
        load_file(big, "user")


def _write(d, name, mid, extra='[launch]\nexec = ["/bin/true"]\n'):
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(f'manifest_version = 1\nid = "{mid}"\nname = "{name}"\nversion = "1.0.0"\n' + extra)


def test_discovery_precedence(tmp_path):
    pkg, adm, usr = tmp_path / "pkg", tmp_path / "adm", tmp_path / "usr"
    _write(pkg, "a.toml", "pub.one")
    _write(pkg, "b.toml", "pub.one")             # duplicate within one directory
    _write(adm, "c.toml", "pub.one")             # admin replaces package
    _write(usr, "d.toml", "pub.one")             # user cannot replace a system id
    _write(usr, "e.toml", "me.mine")
    ms, problems = discover([(pkg, "package"), (adm, "admin"), (usr, "user")])
    assert ms["pub.one"].path == adm / "c.toml"
    assert ms["me.mine"].trust == "user"
    reasons = [(p.path.name, p.severity, p.reason) for p in problems]
    assert any(n == "b.toml" and "duplicate id" in r for n, _s, r in reasons)
    assert any(n == "a.toml" and s == "info" and "replaced by administrator" in r for n, s, r in reasons)
    assert any(n == "d.toml" and "cannot replace system id" in r for n, _s, r in reasons)


def test_rejected_manifest_does_not_stop_discovery(tmp_path):
    d = tmp_path / "pkg"
    _write(d, "a.toml", "pub.ok")
    (d / "b.toml").write_text("not toml [")
    ms, problems = discover([(d, "package")])
    assert list(ms) == ["pub.ok"] and "malformed" in problems[0].reason


def test_resolve_exec_safety(safe_dir, tmp_path):
    from conftest import make_exec

    ok = make_exec(safe_dir / "bin", "app")
    m = parse_text(BASE + f'[launch]\nexec = ["/nonexistent/app"]\nexec_alternatives = [["{ok}", "--x"]]\n')
    assert m.resolve_exec() == ([str(ok), "--x"], "ok", "")
    unsafe = make_exec(tmp_path / "bin", "app")          # /tmp: world-writable ancestor
    if any(os.stat(p).st_mode & 0o002 for p in unsafe.parents):
        m = parse_text(BASE + f'[launch]\nexec = ["{unsafe}"]\n')
        argv, status, reason = m.resolve_exec()
        assert argv is None and status == "unsafe" and "world-writable" in reason
    ww = make_exec(safe_dir / "bin", "ww")
    ww.chmod(0o777)
    m = parse_text(BASE + f'[launch]\nexec = ["{ww}"]\n')
    assert m.resolve_exec()[1] == "unsafe"
