# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Simulation-only tests. UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST."""
import builtins
import os

import pytest

from conftest import BOOKWORM, UBUNTU, make_root
from task_installer import catalog, compat, plan as P, tui
from task_installer.detect import detect, parse_dpkg_status, parse_os_release, pi_family

HW = [("10c4", "ea60", "CP2102 USB to UART Bridge Controller"), ("1546", "01a7", "u-blox 7 - GPS/GNSS Receiver"),
      ("0bda", "2838", "Blog V4"), ("1d6b", "0002", "xHCI Host Controller")]


def test_pi_family_strings():
    assert pi_family("Raspberry Pi 5 Model B Rev 1.0") == "pi5"
    assert pi_family("Raspberry Pi 400 Rev 1.0") == "pi400"
    assert pi_family("Raspberry Pi Zero 2 W Rev 1.0") == "zero2w"
    assert pi_family("Raspberry Pi Zero W Rev 1.1") == "zero"
    assert pi_family("Raspberry Pi Model B Rev 2") == "pi1"
    assert pi_family("Raspberry Pi Compute Module 4 Rev 1.0") == "cm4"
    assert pi_family(None) is None and pi_family("Generic ARM board") is None


def test_parsers():
    assert parse_os_release('ID=debian\nVERSION_CODENAME="trixie"\n# c\nbad line\n') == {"ID": "debian", "VERSION_CODENAME": "trixie"}
    st = "Package: task-core\nStatus: install ok installed\nVersion: 0.3.0\n\nPackage: gone\nStatus: deinstall ok config-files\nVersion: 1\n"
    assert parse_dpkg_status(st) == {"task-core": "0.3.0"}


def test_pi5_detection_recognises_hardware_without_opening(facts, monkeypatch):
    opened = []
    real_open = builtins.open
    monkeypatch.setattr(builtins, "open", lambda f, *a, **k: (opened.append(str(f)), real_open(f, *a, **k))[1])
    f = facts("pi5", usb=HW)
    assert f.pi_family == "pi5" and f.dpkg_arch == "arm64" and f.os_codename == "trixie"
    assert f.mem_total_mib > 7000 and f.graphical and f.bluetooth_adapters == ["hci0"]
    kinds = {u.usb_id: u.kind for u in f.usb}
    assert kinds["10c4:ea60"] == "usb-serial" and kinds["1546:01a7"] == "gps" and kinds["0bda:2838"] == "sdr"
    assert kinds["1d6b:0002"] is None
    assert not any("/dev/" in p for p in opened)


def test_pi5_compatible_verified(facts):
    v = compat.evaluate(facts("pi5"))
    assert v.ok and v.model.status == compat.VERIFIED and v.profile == "full"


def test_pi4_untested_warning(facts):
    v = compat.evaluate(facts("pi4"))
    assert v.ok and v.model.status == compat.UNTESTED and any("untested" in w for w in v.warnings)


def test_pi3_no_webengine_plan_skips_recommends(facts):
    v = compat.evaluate(facts("pi3"))
    assert v.ok and v.profile == "no-webengine"
    pl = P.install_plan(P.select(P.COMPLETE, v), v)
    assert any("--no-install-recommends" in s.argv for s in pl.steps)


def test_zero2w_minimal_only(facts):
    v = compat.evaluate(facts("zero2w"))
    assert v.ok and v.profile == "minimal-only"
    with pytest.raises(ValueError):
        P.select(P.COMPLETE, v)
    ids = [m.id for m in P.select(P.MINIMAL, v)]
    assert ids == ["core", "launcher"]


@pytest.mark.parametrize("model", ["zero", "pi1"])
def test_old_pis_unsupported(facts, model):
    v = compat.evaluate(facts(model, arch="armhf", machine="armv6l"))
    assert not v.ok


def test_armhf_userland_on_64bit_kernel_blocked(facts):
    v = compat.evaluate(facts("pi4", arch="armhf", machine="aarch64"))
    assert not v.ok and any("armhf" in b for b in v.blockers)


@pytest.mark.parametrize("osr", [BOOKWORM, UBUNTU])
def test_wrong_os_blocked(facts, osr):
    assert not compat.evaluate(facts("pi5", os_release=osr)).ok


def test_manual_selection_cannot_bypass_arch_or_os(facts):
    pc = facts(None, arch="amd64", machine="x86_64")
    for fam in compat.MODELS:
        v = compat.evaluate(pc, manual_family=fam)
        assert not v.ok, fam
    v = compat.evaluate(facts("pi5", os_release=BOOKWORM), manual_family="pi5")
    assert not v.ok


def test_manual_selection_only_stricter(facts):
    v = compat.evaluate(facts("pi5"), manual_family="zero2w")
    assert v.manual_mismatch and v.profile == "minimal-only"
    v = compat.evaluate(facts("zero2w"), manual_family="pi5")
    assert v.manual_mismatch and v.profile == "minimal-only"
    v = compat.evaluate(facts("pi5"), manual_family="pi1")
    assert not v.ok


def test_low_disk_blocks(facts):
    f = facts("pi5")
    f.disk_free_mib = 50
    assert not compat.evaluate(f).ok


def test_headless_warns_and_uses_tui(facts):
    v = compat.evaluate(facts("pi5", graphical=False))
    assert v.ok and any("text installer" in w for w in v.warnings)


def test_catalog_never_offers_unfinished_modules():
    names = {m.id for m in catalog.installable()}
    for planned in ("mission", "firmware", "radio-2way", "windows", "weather-decoders"):
        assert planned not in names
    with pytest.raises(ValueError):
        catalog.resolve(["firmware"])
    with pytest.raises(KeyError):
        catalog.resolve(["nope"])


def test_dependencies_auto_selected():
    ids = [m.id for m in catalog.resolve(["mesh", "radio"])]
    assert ids.index("comms") < ids.index("mesh") and "core" in ids and "launcher" in ids
    assert ids.count("comms") == 1


@pytest.mark.parametrize("mode", [P.COMPLETE, P.MINIMAL])
@pytest.mark.parametrize("source", [P.SOURCE_OFFLINE, P.SOURCE_ONLINE])
def test_install_plans_are_safe(facts, mode, source):
    v = compat.evaluate(facts("pi5"))
    pl = P.install_plan(P.select(mode, v), v, source)
    P.assert_safe(pl)
    assert pl.network_required == (source == P.SOURCE_ONLINE)
    if source == P.SOURCE_OFFLINE:
        assert all(not s.network for s in pl.steps)
        checks = [s for s in pl.steps if s.expect == P.LOCAL_URIS_ONLY]
        installs = [s for s in pl.steps if s.argv[:2] == ["apt-get", "install"] and not s.expect]
        assert checks and installs and pl.steps.index(checks[0]) == pl.steps.index(installs[0]) - 1
        assert "--print-uris" in checks[0].argv and not checks[0].root
        assert not any("--no-download" in s.argv for s in pl.steps)   # broken with local .debs in apt 3.0
    assert "NOT enabled" in pl.render() or mode == P.MINIMAL


def test_incompatible_host_cannot_plan(facts):
    v = compat.evaluate(facts("pi5", arch="amd64"))
    with pytest.raises(PermissionError):
        P.select(P.MINIMAL, v)


def test_uninstall_keeps_data_and_never_purges():
    inst = {"task-core": "0.3.0", "task-mesh": "0.3.1", "python3-task-comms": "0.3.1"}
    pl = P.uninstall_plan(inst)
    P.assert_safe(pl)
    argv = pl.steps[0].argv
    assert argv[:2] == ["apt-get", "remove"] and "purge" not in argv and "autoremove" not in argv
    assert "Kept:" in pl.render()
    assert P.uninstall_plan(inst, ["mesh"]).steps[0].argv == ["apt-get", "remove", "task-mesh"]


def test_repair_and_update_plans_safe():
    inst = {"task-core": "0.3.0", "task-mesh": "0.3.1"}
    for pl in (P.repair_plan(inst), P.update_plan(inst, catalog.resolve(["mesh"]))):
        P.assert_safe(pl)
    assert "dpkg" == P.repair_plan(inst).steps[0].argv[0]


def test_assert_safe_rejects_forbidden():
    bad = P.Plan("x", steps=[P.Step("bad", ["apt-get", "purge", "task-core"], root=True)])
    with pytest.raises(AssertionError):
        P.assert_safe(bad)
    bad = P.Plan("x", steps=[P.Step("bad", ["systemctl", "--user", "enable", "task-mesh-service"])])
    with pytest.raises(AssertionError):
        P.assert_safe(bad)


def test_tui_minimal_dry_run(facts):
    f = facts("pi5")
    answers = iter(["y", "install", "minimal", "y"])
    out = []
    rc = tui.interactive(f, inp=lambda _: next(answers), out=out.append)
    text = "\n".join(out)
    assert rc == 0 and "Dry run complete" in text and "task-launcher" in text


def test_tui_custom_rejects_planned_module(facts):
    f = facts("pi5")
    answers = iter(["y", "install", "custom", "firmware"])
    out = []
    assert tui.interactive(f, inp=lambda _: next(answers), out=out.append) == 2
    assert any("not installable" in o for o in out)


def test_tui_offers_repair_when_installed(facts):
    st = "Package: task-core\nStatus: install ok installed\nVersion: 0.3.0\n"
    f = facts("pi5", dpkg_status=st)
    answers = iter(["y", "uninstall", "y"])
    out = []
    assert tui.interactive(f, inp=lambda _: next(answers), out=out.append) == 0
    assert any("apt-get remove task-core" in o for o in out)


def test_tui_incompatible_stops(facts):
    f = facts("pi5", arch="armhf")
    out = []
    answers = iter(["y"])
    assert tui.interactive(f, inp=lambda _: next(answers), out=out.append) == 2
    assert any("Nothing was changed" in o for o in out)


def test_cli_detect_json(facts, monkeypatch, capsys):
    f = facts("pi5")
    monkeypatch.setattr(tui, "detect", lambda root: f)
    assert tui.main(["detect", "--json"]) == 0
    assert '"pi_family": "pi5"' in capsys.readouterr().out
    assert tui.main(["--model", "zero2w", "plan", "--mode", "minimal"]) == 0


def test_real_detect_on_this_machine_is_read_only():
    # Runs real detection against "/" of the build machine; only checks it does not crash.
    f = detect("/")
    assert f.python_version
