# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Milestone B installer additions. Simulation only. UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST."""
import hashlib
import json
import shutil
import subprocess

import pytest

from conftest import DEBIAN_13_6, TRIXIE, make_root
from task_installer import bundle as B, compat, debver, plan as P, preflight as PF, tui
from task_installer.catalog import BY_ID
from task_installer.detect import detect, parse_revision

NOTIFIER = "/usr/lib/task-mesh/task_mesh/hub/notifier.py"
VERIFY_NOTIFIER = f"??5??????   {NOTIFIER}\n"


@pytest.mark.parametrize("a,b", [("0.3.1", "0.3.2~alpha1"), ("0.3.2~alpha1", "0.3.2"), ("0.3.2", "0.3.2-1"),
                                 ("1:0.1", "2.0"), ("0.3.10", "0.3.9"), ("0.3.0", "0.3.0"), ("1.0~rc1", "1.0~rc1+b1"),
                                 ("2.0a", "2.0+"), ("0.2.4", "0.2.4.1"), ("7.1.5-0+deb13u1", "7.1.5-0+deb13u2")])
def test_debver_matches_dpkg(a, b):
    mine = debver.compare(a, b)
    if shutil.which("dpkg"):
        lt = subprocess.run(["dpkg", "--compare-versions", a, "lt", b]).returncode == 0
        eq = subprocess.run(["dpkg", "--compare-versions", a, "eq", b]).returncode == 0
        assert mine == (0 if eq else (-1 if lt else 1))
    assert debver.compare(b, a) == -mine


@pytest.mark.parametrize("rev,family,mem", [("d04170", "pi5", 8192), ("c04170", "pi5", 4096), ("c03115", "pi4", 4096),
                                            ("b03114", "pi4", 2048), ("a03111", "pi4", 1024), ("c03130", "pi400", 4096),
                                            ("a020d3", "pi3", 1024), ("902120", "zero2w", 512), ("d03140", "cm4", 8192)])
def test_revision_codes(rev, family, mem):
    assert parse_revision(f"processor\t: 0\nRevision\t: {rev}\nSerial\t: 1\n") == (rev, family, mem)


def test_revision_absent_or_old_style():
    assert parse_revision("") == (None, None, None)
    assert parse_revision("Revision : 000e\n")[1] == "pi1"


def _facts(tmp_path, model="pi5", rev=None, arch="arm64", dpkg_status="", extra=()):
    root = make_root(tmp_path, model, dpkg_status=dpkg_status)
    if rev:
        (root / "proc/cpuinfo").write_text(f"Revision\t: {rev}\n")
    for rel, text in extra:
        f = root / rel.lstrip("/")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    env = {"DISPLAY": ":0"}
    if arch is None:
        return detect(root, env=env), root
    return detect(root, env=env, runner=lambda argv: arch, kernel_machine="aarch64"), root


def test_simulated_root_never_queries_build_host(tmp_path):
    root = make_root(tmp_path, "pi5")
    f = detect(root, env={})
    assert f.simulated and f.dpkg_arch is None                     # unknown, not the build host's amd64
    assert not compat.evaluate(f).ok
    (root / "var/lib/dpkg/arch-native").write_text("arm64\n")
    assert detect(root, env={}).dpkg_arch == "arm64"


def test_revision_mismatch_is_warned_and_stricter(tmp_path):
    f, _ = _facts(tmp_path, "pi5", rev="902120")                  # model says Pi 5, revision says Zero 2 W
    v = compat.evaluate(f)
    assert any("disagree" in w for w in v.warnings) and v.profile == "minimal-only"


def test_pi4_1gb_drops_webengine(tmp_path):
    root = make_root(tmp_path, "pi4")
    (root / "proc/meminfo").write_text("MemTotal:  950000 kB\n")
    f = detect(root, env={"DISPLAY": ":0"}, runner=lambda argv: "arm64")
    v = compat.evaluate(f)
    assert v.ok and v.profile == "no-webengine" and any("QtWebEngine" in w for w in v.warnings)


def test_manual_selection_cannot_bypass_arch_or_os(tmp_path):
    f, _ = _facts(tmp_path, "pi5", arch="armhf")
    for fam in ("pi5", "pi4"):
        assert not compat.evaluate(f, fam).ok


def make_bundle(tmp_path, versions=None, corrupt=None):
    d = tmp_path / "bundle"
    d.mkdir(exist_ok=True)
    versions = versions or {"task-core": "0.3.0", "task-core-compat": "0.3.0", "task-launcher": "0.3.7",
                            "python3-task-comms": "0.3.1", "task-mesh": "0.3.2~alpha1"}
    pk = []
    for n, v in versions.items():
        fn = f"{n}_{v}_all.deb"
        data = f"fake {n} {v}".encode()
        (d / fn).write_bytes(data)
        pk.append({"name": n, "version": v, "file": fn, "sha256": hashlib.sha256(data).hexdigest(), "depends": ""})
    (d / "BUNDLE.json").write_text(json.dumps({"format": 1, "packages": pk}))
    if corrupt:
        (d / f"{corrupt}_{versions[corrupt]}_all.deb").write_bytes(b"tampered")
    return B.load(d)


STATUS_PI = "".join(f"Package: {n}\nStatus: install ok installed\nVersion: {v}\n\n" for n, v in [
    ("task-core", "0.3.0"), ("task-core-compat", "0.3.0"), ("task-launcher", "0.3.7"), ("python3-task-comms", "0.3.1"),
    ("task-mesh", "0.3.1")])


def test_bundle_rejects_unsafe_names(tmp_path):
    d = tmp_path / "b"
    d.mkdir()
    (d / "BUNDLE.json").write_text(json.dumps({"packages": [{"name": "x", "version": "1", "file": "../x.deb", "sha256": "0"}]}))
    with pytest.raises(ValueError):
        B.load(d)


def test_preflight_upgrade_with_maintained_notifier(tmp_path):
    notifier_text = "pi modified notifier\n"
    f, root = _facts(tmp_path, dpkg_status=STATUS_PI, extra=[(NOTIFIER, notifier_text)])
    b = make_bundle(tmp_path)
    PF.MAINTAINED[NOTIFIER] = ("task-mesh", "0.3.2~alpha1", hashlib.sha256(notifier_text.encode()).hexdigest())
    try:
        pf = PF.check(f, list(b.packages), b, VERIFY_NOTIFIER, root)
    finally:
        PF.MAINTAINED[NOTIFIER] = ("task-mesh", "0.3.2~alpha1",
                                   "2864d2425cee7be738863139f4edb1a6d9fd83345693a5690503a46c933bbe1a")
    assert pf.ok and pf.upgrades == {"task-mesh": ("0.3.1", "0.3.2~alpha1")}
    assert pf.modified_files == [NOTIFIER] and any("same" in w and "maintained" in w for w in pf.warnings)
    v = compat.evaluate(f)
    mods = P.select(P.COMPLETE, v)
    plan = P.update_plan(f.installed_task_packages, [m for m in mods if set(m.packages) <= set(b.packages)], b, pf)
    P.assert_safe(plan)
    steps = [s.argv for s in plan.steps]
    backup = [a for a in steps if a[0] == "cp"]
    assert backup and NOTIFIER in backup[0]
    assert steps.index(backup[0]) < steps.index([a for a in steps if a[0] == "apt-get"][0])
    install = [a for a in steps if a[0] == "apt-get"][0]
    assert all("*" not in a for a in install) and f"{b.directory}/task-mesh_0.3.2~alpha1_all.deb" in install


def test_preflight_blocks_downgrade_and_corrupt_bundle(tmp_path):
    status = STATUS_PI.replace("Version: 0.3.7", "Version: 0.3.9")
    f, root = _facts(tmp_path, dpkg_status=status)
    b = make_bundle(tmp_path, corrupt="task-core")
    pf = PF.check(f, list(b.packages), b, None, root)
    assert not pf.ok
    assert any("downgrade" in x for x in pf.blockers) and any("checksum mismatch" in x for x in pf.blockers)
    with pytest.raises(PermissionError):
        P.install_plan(P.select(P.MINIMAL, compat.evaluate(f)), compat.evaluate(f), bundle=b, preflight=pf)


def test_preflight_missing_package_and_shadowing(tmp_path):
    f, root = _facts(tmp_path, extra=[("/usr/local/bin/task-console", "#!/bin/sh\n")])
    b = make_bundle(tmp_path)
    pf = PF.check(f, ["task-console"], b, None, root)
    assert any("does not contain task-console" in x for x in pf.blockers)
    assert any("/usr/local/bin/task-console" in w and "shadow" in w for w in pf.warnings)


def test_fresh_install_plan_uses_exact_files(tmp_path):
    f, root = _facts(tmp_path)
    b = make_bundle(tmp_path)
    v = compat.evaluate(f)
    mods = P.select(P.MINIMAL, v)
    pf = PF.check(f, P._packages(mods), b, None, root)
    plan = P.install_plan(mods, v, P.SOURCE_OFFLINE, bundle=b, preflight=pf)
    P.assert_safe(plan)
    apt = [s.argv for s in plan.steps if s.argv[0] == "apt-get" and not s.expect][0]
    assert all(a.startswith("-") or a.startswith(str(b.directory)) for a in apt[2:])
    assert not [s for s in plan.steps if s.argv[0] == "cp"]     # nothing modified -> no backup step


@pytest.mark.parametrize("argv", [["rm", "-rf", "/"], ["pip", "install", "x"], ["python3", "-m", "pip"],
                                  ["apt-get", "install", "--force-yes", "x"], ["esptool.py", "write_flash"],
                                  ["systemctl", "--user", "enable", "task-mesh-service"], ["apt-get", "autoremove"]])
def test_assert_safe_forbids(argv):
    with pytest.raises(AssertionError):
        P.assert_safe(P.Plan("x", steps=[P.Step("bad", argv)]))


def test_recovery_plan_is_safe_and_keeps_data():
    plan = P.recovery_plan({"task-mesh": "0.3.2~alpha1", "task-core": "0.3.0"})
    P.assert_safe(plan)
    flat = [a for s in plan.steps for a in s.argv]
    assert "--allow-downgrades" in flat and "purge" not in flat and "autoremove" not in flat
    assert any("never restarts" in n for n in plan.notes)


def test_dpkg_verify_parser():
    text = f"{VERIFY_NOTIFIER}??5?????? c /etc/task/core.toml\nmissing   /usr/bin/x\n"
    assert PF.parse_dpkg_verify(text) == [NOTIFIER, "/etc/task/core.toml"]


def test_cli_preflight_and_plan_with_bundle(tmp_path, capsys):
    root = make_root(tmp_path, "pi5", dpkg_status=STATUS_PI)
    (root / "var/lib/dpkg/arch-native").write_text("arm64\n")
    b = make_bundle(tmp_path)
    vf = tmp_path / "verify.txt"
    vf.write_text(VERIFY_NOTIFIER)
    rc = tui.main(["--root", str(root), "--bundle", str(b.directory), "--dpkg-verify", str(vf), "preflight",
                   "--mode", "minimal"])
    out = capsys.readouterr().out
    assert rc == 0 and "Preflight: OK" in out and "same version" in out
    rc = tui.main(["--root", str(root), "--bundle", str(b.directory), "recovery"])
    assert rc == 0 and "--allow-downgrades" in capsys.readouterr().out


def test_backup_only_for_packages_actually_overwritten(tmp_path):
    f, root = _facts(tmp_path, dpkg_status=STATUS_PI, extra=[(NOTIFIER, "x\n")])
    b = make_bundle(tmp_path)
    pf = PF.check(f, ["task-core", "task-launcher"], b, VERIFY_NOTIFIER, root)      # same versions, no mesh
    assert pf.ok and pf.modified_files == [] and not pf.upgrades
    pf = PF.check(f, ["task-mesh"], b, VERIFY_NOTIFIER, root, action="repair")
    assert pf.modified_files == [NOTIFIER]
    info = root / "var/lib/dpkg/info"
    info.mkdir(parents=True)
    (info / "task-core.list").write_text("/usr/bin/task-core\n")
    (info / "task-mesh.list").write_text(NOTIFIER + "\n")
    pf = PF.check(f, ["task-core"], b, VERIFY_NOTIFIER, root, action="repair")
    assert pf.modified_files == []                                                    # owned by task-mesh: untouched


def test_check_local_uris():
    out = ("'file:/b/task-core_0.3.0_all.deb' task-core_0.3.0_all.deb 45324 \n"
           "'http://deb.debian.org/debian/pool/main/p/pyyaml/python3-yaml_6.0.2-1%2bb2_arm64.deb' x 1 MD5Sum:0\n")
    assert P.check_local_uris(out) == ["http://deb.debian.org/debian/pool/main/p/pyyaml/python3-yaml_6.0.2-1%2bb2_arm64.deb"]
    assert P.check_local_uris("'file:/b/a.deb' a.deb 1 \n") == []
    assert P.check_local_uris("") == []


@pytest.mark.parametrize("make", ["update", "repair", "recovery"])
def test_every_offline_apt_step_is_guarded(make):
    installed = {"task-core": "0.3.0", "task-mesh": "0.3.1"}
    if make == "update":
        pl = P.update_plan(installed, [BY_ID["core"], BY_ID["mesh"]])
    elif make == "repair":
        pl = P.repair_plan(installed)
    else:
        pl = P.recovery_plan(installed)
    for i, s in enumerate(pl.steps):
        if s.argv[:2] == ["apt-get", "install"] and not s.expect:
            prev = pl.steps[i - 1]
            assert prev.expect == P.LOCAL_URIS_ONLY and prev.argv[4:] == s.argv[2:]


def test_development_pi_baseline_20261122_is_accepted(tmp_path):
    """Pi 5 Model B Rev 1.0, revision d04170, arm64, Debian 13.6 trixie with plain Debian os-release (ID=debian)."""
    root = make_root(tmp_path, model="pi5", os_release=DEBIAN_13_6)
    (root / "proc/cpuinfo").write_text("processor\t: 0\nRevision\t: d04170\n")
    (root / "var/lib/dpkg").mkdir(parents=True, exist_ok=True)
    (root / "var/lib/dpkg/arch-native").write_text("arm64\n")
    f = detect(str(root))
    assert f.dpkg_arch == "arm64"
    assert (f.os_id, f.os_codename, f.os_version_id) == ("debian", "trixie", "13")
    assert f.revision == "d04170" and f.revision_family == "pi5" and f.revision_mem_mib == 8192
    v = compat.evaluate(f)
    assert v.ok and v.profile == "full" and not v.blockers
