# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Installer hardening tests: the REAL preflight/install/rollback scripts run against fake apt-get/dpkg/
dpkg-query/apt-mark/sudo/id/pgrep (TASK_INSTALLER_TESTBIN) and real dummy .debs built with dpkg-deb.
Scenarios: simulation failure, Remv/Purg lines, downgrades, broken deps, wrong arch/OS, typed confirmation,
backup contents (settings, dpkg state, rollback debs, SQLite set), rollback incl. --restore-data, SoapySDR
warning without apt-mark, static safety checks. Nothing here can touch the real system."""

import os
import re
import shlex
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

COMMON = Path(__file__).resolve().parents[1]
RELEASE = COMMON.parent

# Fake tools. They read their knobs from the fixture's fake.conf (absolute path baked in at creation), because
# the production scripts run them in a scrubbed environment (env -i) and read NO test knobs themselves.
FAKE_HEAD = '#!/bin/bash\n. "@FX@/fake.conf"\n'
FAKES = {
    "apt-get": r'''echo "APT-GET $*" >> "$FAKE_LOG"
for a in "$@"; do [ "$a" = -s ] && sim=1; done
if [ -n "${sim:-}" ]; then
    [ -f "${FAKE_SIM:-/nonexistent}" ] && cat "$FAKE_SIM"
    exit "${FAKE_SIM_RC:-0}"
fi
for a in "$@"; do
    case "$a" in *.deb)
        p=$(/usr/bin/dpkg-deb -f "$a" Package); v=$(/usr/bin/dpkg-deb -f "$a" Version)
        /usr/bin/grep -v "^$p " "$FAKE_STATE" > "$FAKE_STATE.n" || true
        echo "$p $v" >> "$FAKE_STATE.n"; mv "$FAKE_STATE.n" "$FAKE_STATE";;
    esac
done
exit "${FAKE_INSTALL_RC:-0}"
''',
    "dpkg-query": r'''last="${@: -1}"
if [[ "$last" == -* ]] || [[ "$last" == *'${'* ]]; then
    while read -r p v; do printf '%s\t%s\tinstall ok installed\n' "$p" "$v"; done < "$FAKE_STATE"; exit 0
fi
v=$(/usr/bin/awk -v p="$last" '$1==p{print $2}' "$FAKE_STATE")
[ -n "$v" ] || exit 1
echo "install ok installed $v"
''',
    "dpkg": r'''case "$1" in
  --print-architecture) [ "${FAKE_ARCH-arm64}" = FAIL ] && exit 2; echo "${FAKE_ARCH-arm64}";;
  -l) echo "ii fake-dpkg-l-snapshot";;
  *) exec "@FX@/real-dpkg" "$@";;
esac
''',
    "apt-mark": r'''echo "APT-MARK $*" >> "$FAKE_LOG"
case "$1" in showauto) cat "${FAKE_AUTO:-/dev/null}";; showmanual) echo "manual-pkg";; *) exit 9;; esac
''',
    "sudo": 'echo "SUDO $*" >> "$FAKE_LOG"\nexec "$@"\n',
    "id": 'echo "${FAKE_UID:-1000}"\n',
    "pgrep": 'for a in "$@"; do pat="$a"; done\n[ -n "${FAKE_RUNNING:-}" ] && [[ "$FAKE_RUNNING" == *"$pat"* ]] && exit 0\nexit 1\n',
}


def build_deb(out, pkg, ver, arch="all"):
    d = out.parent / f"build-{pkg}-{ver}-{arch}"
    (d / "DEBIAN").mkdir(parents=True)
    (d / "DEBIAN/control").write_text(f"Package: {pkg}\nVersion: {ver}\nArchitecture: {arch}\n"
                                      "Maintainer: test <t@t>\nDescription: dummy\n")
    subprocess.run(["/usr/bin/dpkg-deb", "--root-owner-group", "-b", str(d), str(out)], check=True,
                   capture_output=True)
    shutil.rmtree(d)
    return out


CONF = '''REL_ID="test-demo-2.0"
REL_TITLE="T.A.S.K. demo 2.0 (test)"
TARGETS=("task-demo=2.0")
DEBS=("debs/task-demo_2.0_all.deb")
REQUIRES=("task-base>=1.0")
ROLLBACK=("task-demo=1.0=rollback/task-demo_1.0_all.deb")
SETTINGS=(".config/task-demo")
SQLITE=(".local/share/task-demo/index.sqlite")
CLOSE_FIRST=("task_demo")
WARN_RUNNING=("task_launcher")
SOAPY_WARN=1
'''


DEBIAN13 = ('PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nNAME="Debian GNU/Linux"\nVERSION_ID="13"\n'
            'VERSION="13 (trixie)"\nVERSION_CODENAME=trixie\nDEBIAN_VERSION_FULL=13.3\nID=debian\n'
            'HOME_URL="https://www.debian.org/"\n')
TOOLS = ("apt-get", "apt-mark", "dpkg", "dpkg-query", "sudo", "id", "pgrep")
# Runs a command inside a PRIVATE user+mount namespace in which the fixture's fake tools and os-release are
# bind-mounted over the real /usr/bin/<tool> and /etc/os-release. The mounts exist only in that namespace and
# vanish with it; the real system is never touched. This is the ONLY way the tests change what the scripts see.
NS = r'''set -e
fx="$1"; shift
for t in apt-get apt-mark dpkg dpkg-query sudo id pgrep; do /usr/bin/mount --bind "$fx/bin/$t" "/usr/bin/$t"; done
if [ -f "$fx/os-release" ]; then /usr/bin/mount --bind "$fx/os-release" /etc/os-release
else /usr/bin/mount -t tmpfs fixture-no-etc /etc; fi
exec "$@"
'''


@pytest.fixture
def env(tmp_path):
    rel = tmp_path / "zip"
    (rel / "debs").mkdir(parents=True)
    (rel / "rollback").mkdir()
    (rel / "tools").mkdir()
    for f in ("preflight.sh", "install.sh", "rollback.sh", "task-guard.sh"):
        shutil.copy2(COMMON / f, rel / f)
    for f in (COMMON / "tools").iterdir():
        if f.is_file():
            shutil.copy2(f, rel / "tools" / f.name)
    (rel / "release.conf").write_text(CONF)
    build_deb(rel / "debs/task-demo_2.0_all.deb", "task-demo", "2.0")
    build_deb(rel / "rollback/task-demo_1.0_all.deb", "task-demo", "1.0")
    sums = subprocess.run(["/usr/bin/sha256sum", "debs/task-demo_2.0_all.deb", "rollback/task-demo_1.0_all.deb",
                           "release.conf", "preflight.sh", "install.sh", "rollback.sh", "task-guard.sh"],
                          cwd=rel, capture_output=True, text=True, check=True).stdout
    (rel / "SHA256SUMS").write_text(sums)
    fx = tmp_path / "fixture"
    (fx / "bin").mkdir(parents=True)
    shutil.copy2("/usr/bin/dpkg", fx / "real-dpkg")
    for name, body in FAKES.items():
        (fx / "bin" / name).write_text((FAKE_HEAD + body).replace("@FX@", str(fx)))
        (fx / "bin" / name).chmod(0o755)
    (fx / "os-release").write_text(DEBIAN13)
    home = tmp_path / "home"
    (home / ".config/task-demo").mkdir(parents=True)
    (home / ".config/task-demo/prefs.json").write_text('{"v": 1}')
    db = home / ".local/share/task-demo/index.sqlite"
    db.parent.mkdir(parents=True)
    c = sqlite3.connect(db)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE t(x)")
    c.executemany("INSERT INTO t VALUES(?)", [(i,) for i in range(10)])
    c.commit()
    c.close()
    state = tmp_path / "state"
    state.write_text("task-base 1.2\ntask-demo 1.0\n")
    sim = tmp_path / "sim.txt"
    sim.write_text("Inst task-demo [1.0] (2.0 local-deb [all])\nConf task-demo (2.0 local-deb [all])\n")
    (tmp_path / "log").write_text("")
    base = {"FAKE_LOG": str(tmp_path / "log"), "FAKE_STATE": str(state), "FAKE_SIM": str(sim)}
    e = {"HOME": str(home), "PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}
    return {"rel": rel, "env": e, "home": home, "state": state, "sim": sim, "log": tmp_path / "log", "db": db,
            "tmp": tmp_path, "fx": fx, "base": base}


def set_knobs(env, **knobs):
    conf = dict(env["base"], **{k: str(v) for k, v in knobs.items()})
    (env["fx"] / "fake.conf").write_text("".join(f"{k}={shlex.quote(v)}\n" for k, v in conf.items()))


def run(env, script, *args, inp="", via_bash=False, extra_env=None, **knobs):
    """Run a REAL script inside the fixture namespace. knobs configure the fake tools only."""
    set_knobs(env, **knobs)
    path = script if os.path.isabs(script) else str(env["rel"] / script)
    cmd = ["/bin/bash", path, *args] if via_bash else [path, *args]
    e = dict(env["env"], **(extra_env or {}))
    return subprocess.run(["/usr/bin/unshare", "--user", "--map-root-user", "--mount", "/bin/bash", "-c", NS, "ns",
                           str(env["fx"]), *cmd], env=e, input=inp, capture_output=True, text=True, timeout=120)


def log(env):
    return env["log"].read_text()


def test_i01_preflight_passes_clean_and_changes_nothing(env):
    before = env["state"].read_text()
    r = run(env, "preflight.sh")
    assert r.returncode == 0, r.stdout
    assert "PREFLIGHT PASSED" in r.stdout and "TEST MODE" not in r.stdout
    assert "OK    host architecture: arm64" in r.stdout
    assert "OK    host OS: ID=debian VERSION_ID=13 VERSION_CODENAME=trixie" in r.stdout
    assert env["state"].read_text() == before
    assert "SUDO" not in log(env) and re.search(r"APT-GET -s -o Debug::NoLocking=1 install --no-remove ", log(env))


@pytest.mark.parametrize("rc", [1, 100])
def test_i02_simulation_nonzero_exit_fails(env, rc):
    r = run(env, "preflight.sh", FAKE_SIM_RC=str(rc))
    assert r.returncode == 1 and f"apt-get simulation exited {rc}" in r.stdout and "PREFLIGHT FAILED" in r.stdout


@pytest.mark.parametrize("line", ["Remv python3-soapysdr [0.8.1-5]", "Purg kiwix-tools [14.0.0-1]"])
def test_i03_remv_purg_lines_fail_even_with_exit_0(env, line):
    env["sim"].write_text(env["sim"].read_text() + line + "\n")
    r = run(env, "preflight.sh")
    assert r.returncode == 1 and "apt would REMOVE something: " + line in r.stdout


def test_i04_downgrades_rejected(env):
    env["state"].write_text("task-base 1.2\ntask-demo 3.0\n")         # newer installed than the zip
    r = run(env, "preflight.sh")
    assert r.returncode == 1 and "task-demo 3.0 is newer than 2.0: refusing to downgrade" in r.stdout
    env["state"].write_text("task-base 1.2\ntask-demo 1.0\n")
    env["sim"].write_text(env["sim"].read_text() + "Inst python3-numpy [1:2.2.4+ds-1] (1:1.26.0-1 x [arm64])\n")
    r = run(env, "preflight.sh")
    assert r.returncode == 1 and "apt would DOWNGRADE python3-numpy 1:2.2.4+ds-1 -> 1:1.26.0-1" in r.stdout


def test_i05_broken_or_missing_dependencies_fail(env):
    env["sim"].write_text("E: Unable to correct problems, you have held broken packages.\n")
    r = run(env, "preflight.sh", FAKE_SIM_RC="100")
    assert r.returncode == 1 and "broken or unmet" in r.stdout
    env["sim"].write_text("Inst task-demo [1.0] (2.0 local-deb [all])\n")
    env["state"].write_text("task-demo 1.0\n")                          # required task-base missing
    r = run(env, "preflight.sh")
    assert r.returncode == 1 and "task-base not installed < 1.0" in r.stdout


def test_i06_wrong_deb_arch_fails(env):
    build_deb(env["rel"] / "debs/task-demo_2.0_all.deb", "task-demo", "2.0", arch="amd64")
    r = run(env, "preflight.sh")
    assert r.returncode == 1 and "Architecture 'amd64' is not all/arm64" in r.stdout


def test_i07_sha_mismatch_fails(env):
    with open(env["rel"] / "release.conf", "a") as f:
        f.write("# tampered\n")
    r = run(env, "preflight.sh")
    assert r.returncode == 1 and "SHA256SUMS mismatch" in r.stdout


def test_i08_install_check_mode_and_wrong_confirmation_change_nothing(env):
    before = env["state"].read_text()
    r = run(env, "install.sh")
    assert r.returncode == 0 and "Check only; nothing changed" in r.stdout
    for answer in ("", "yes", "y", "install test-demo-2.0", "INSTALL test-demo-2.0 "):
        r = run(env, "install.sh", "--install", inp=answer + "\n")
        assert r.returncode == 1 and "Not confirmed; nothing changed." in r.stdout
    assert env["state"].read_text() == before and "SUDO" not in log(env)
    assert not (env["home"] / "task-backups").exists()
    r = run(env, "install.sh", "--install", FAKE_UID="0")
    assert r.returncode == 2 and "not root" in r.stdout


def test_i09_running_program_blocks_install(env):
    r = run(env, "install.sh", "--install", inp="INSTALL test-demo-2.0\n", FAKE_RUNNING="python3 -m task_demo")
    assert r.returncode == 1 and "close the running program matching 'task_demo'" in r.stdout


def _install(env):
    r = run(env, "install.sh", "--install", inp="INSTALL test-demo-2.0\n")
    assert r.returncode == 0, r.stdout + r.stderr
    (b,) = list((env["home"] / "task-backups").iterdir())
    return r, b


def test_i10_install_backs_up_everything_then_one_apt_call(env):
    db_before = env["db"].read_bytes()
    r, b = _install(env)
    assert env["state"].read_text().splitlines()[-1] == "task-demo 2.0"
    assert (b / "versions-before.txt").read_text() == "task-demo 1.0\n"
    assert (b / "home/.config/task-demo/prefs.json").read_text() == '{"v": 1}'
    for f in ("dpkg-l.txt", "dpkg-query.tsv", "apt-mark-manual.txt", "apt-mark-auto.txt", "architecture.txt",
              "os-release"):
        assert (b / "dpkg-state" / f).is_file(), f
    assert (b / "rollback-debs/task-demo_1.0_all.deb").is_file()
    assert subprocess.run(["/usr/bin/sha256sum", "-c", "SHA256SUMS"], cwd=b / "rollback-debs").returncode == 0
    bk = b / "sqlite/.local/share/task-demo/index.sqlite"
    c = sqlite3.connect(bk)
    assert c.execute("SELECT count(*) FROM t").fetchone()[0] == 10 and c.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    c.close()
    assert not Path(str(bk) + "-wal").exists()
    assert env["db"].read_bytes() == db_before
    assert sorted(p.name for p in env["db"].parent.iterdir()) == ["index.sqlite"]   # nothing created beside it
    for f in ("rollback.sh", "task-guard.sh", "release.conf", "tools/sqlite_backup.py", "tools/rosnap.py"):
        assert (b / f).is_file()
    installs = [ln for ln in log(env).splitlines() if ln.startswith("SUDO")]
    assert len(installs) == 1 and installs[0].startswith("SUDO ") and " install --no-remove " in installs[0]
    assert "-y" not in installs[0].split() and "autoremove" not in log(env) and "systemctl" not in log(env)
    assert "OK    task-demo 2.0" in r.stdout and "No service was started" in r.stdout


def test_i11_missing_rollback_package_blocks_install(env):
    env["state"].write_text("task-base 1.2\ntask-demo 1.5\n")          # no rollback deb for 1.5 in the zip
    r = run(env, "install.sh", "--install", inp="INSTALL test-demo-2.0\n")
    assert r.returncode == 1 and "no rollback package for 1.5" in r.stdout and "SUDO" not in log(env)


def test_i12_rollback_explicit_simulated_confirmed_and_restores_data(env):
    _, b = _install(env)
    (env["home"] / ".config/task-demo/prefs.json").write_text('{"v": 2}')
    c = sqlite3.connect(env["db"])
    c.execute("INSERT INTO t VALUES(99)")
    c.commit()
    c.close()
    rb = str(b / "rollback.sh")
    r = run(env, rb)
    assert r.returncode == 2 and "usage" in r.stdout
    env["sim"].write_text("Inst task-demo [2.0] (1.0 local-deb [all])\nRemv task-base [1.2]\n")
    r = run(env, rb, str(b))
    assert r.returncode == 1 and "ROLLBACK REFUSED" in r.stdout and "apt would REMOVE" in r.stdout
    env["sim"].write_text("Inst task-demo [2.0] (1.0 local-deb [all])\nInst task-base [1.2] (1.0 x [all])\n")
    r = run(env, rb, str(b))
    assert r.returncode == 1 and "apt would DOWNGRADE task-base" in r.stdout      # only rollback pkgs may go down
    env["sim"].write_text("Inst task-demo [2.0] (1.0 local-deb [all])\n")
    r = run(env, rb, str(b), "--restore-data", inp="yes\n")
    assert r.returncode == 1 and "Not confirmed" in r.stdout and "task-demo 2.0" in env["state"].read_text()
    r = run(env, rb, str(b), "--restore-data", inp="ROLLBACK test-demo-2.0\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "rollback downgrade task-demo 2.0 -> 1.0 (explicitly requested)" in r.stdout
    assert "task-demo 1.0" in env["state"].read_text()
    assert [ln for ln in log(env).splitlines() if ln.startswith("SUDO")][-1].count("--allow-downgrades") == 1
    assert (env["home"] / ".config/task-demo/prefs.json").read_text() == '{"v": 1}'
    aside = list((env["home"] / ".config").glob("task-demo.pre-rollback-*"))
    assert len(aside) == 1 and (aside[0] / "prefs.json").read_text() == '{"v": 2}'     # moved, never deleted
    c = sqlite3.connect(env["db"])
    assert c.execute("SELECT count(*) FROM t").fetchone()[0] == 10
    c.close()
    sets = list(env["db"].parent.glob("pre-rollback-*"))
    assert len(sets) == 1 and (sets[0] / "index.sqlite").is_file()


def test_i13_package_not_installed_before_is_never_removed(env):
    env["state"].write_text("task-base 1.2\n")
    env["sim"].write_text("Inst task-demo (2.0 local-deb [all])\n")
    _, b = _install(env)
    assert (b / "versions-before.txt").read_text() == "task-demo none\n"
    r = run(env, str(b / "rollback.sh"), str(b))
    assert r.returncode == 0 and "was not installed before" in r.stdout and "Nothing to roll back" in r.stdout
    assert not re.search(r"\b(remove|purge|autoremove)\b", " ".join(ln.replace("--no-remove", "") for ln in log(env).splitlines() if ln.startswith("SUDO")))


def test_i14_soapy_auto_marked_warns_but_never_apt_marks(env, tmp_path):
    env["state"].write_text(env["state"].read_text() + "python3-soapysdr 0.8.1-5+b4\n")
    auto = tmp_path / "auto"
    auto.write_text("python3-soapysdr\n")
    r = run(env, "preflight.sh", FAKE_AUTO=str(auto))
    assert r.returncode == 0 and "marked automatically installed" in r.stdout
    assert "sudo apt-mark manual python3-soapysdr" in r.stdout
    assert [ln for ln in log(env).splitlines() if ln.startswith("APT-MARK")] == ["APT-MARK showauto"]


CONFS = sorted(RELEASE.glob("corrections/*/release.conf"))
SCRIPTS = sorted(list(COMMON.glob("*.sh")) + CONFS)


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: str(p.relative_to(RELEASE)))
def test_i15_static_safety(path):
    src = path.read_text()
    code = "\n".join(ln.split("#", 1)[0] if not ln.lstrip().startswith(("tg_say", "tg_warn", "tg_ok", "tg_fail",
                     "echo", "printf")) else "" for ln in src.splitlines())
    for bad in ("autoremove", "systemctl", "service ", "apt-mark manual", "apt-mark auto", "eval ", "purge",
                " remove ", "rm -rf", "/etc/rain", "-y ", "--yes", "dpkg -i", "dpkg --install", "curl", "wget"):
        assert bad not in code, (path.name, bad)
    for override in ("TESTBIN", "TASK_OS_RELEASE", "TASK_INSTALLER", "FIXTURE", "TEST_MODE", "TEST MODE",
                     "${OS_RELEASE:-", "${DPKG:-", "${APT_GET:-", "tg_bin"):
        assert override not in src, (path.name, override)       # no override mechanism exists at all


def test_i16_real_release_confs_are_consistent():
    assert len(CONFS) == 6  # medical-0.3.6, medical-reader-0.3.7, sdr-0.2.0-r2, sdr-0.2.2, sdr-0.2.3, sdr-0.2.4 (consolidated tree)
    for c in CONFS:
        dump = subprocess.run(["/bin/bash", "-c", '. "$1"; for v in "${TARGETS[@]}"; do echo "T $v"; done; '
                               'for v in "${DEBS[@]}"; do echo "D $v"; done; for v in "${ROLLBACK[@]}"; do '
                               'echo "R $v"; done; echo "ID $REL_ID"', "x", str(c)],
                              capture_output=True, text=True, check=True).stdout.split("\n")
        t = [ln[2:] for ln in dump if ln.startswith("T ")]
        d = [ln[2:] for ln in dump if ln.startswith("D ")]
        r = [ln[2:] for ln in dump if ln.startswith("R ")]
        assert t and len(t) == len(d) and r
        for pv, deb in zip(t, d):
            p, v = pv.split("=")
            assert deb == f"debs/{p}_{v}_all.deb"
        for rb in r:
            p, v, f = rb.split("=")
            assert f == f"rollback/{p}_{v}_all.deb" and p in {x.split("=")[0] for x in t}


def test_i24_sdr_023_rollback_chain_and_settings():
    c = RELEASE / "corrections/sdr-0.2.3/release.conf"
    out = subprocess.run(["/bin/bash", "-c", '. "$1"; printf "%s\\n" "${ROLLBACK[@]}"; echo "S ${SETTINGS[*]}"', "x",
                          str(c)], capture_output=True, text=True, check=True).stdout.splitlines()
    assert [ln.split("=")[1] for ln in out if ln.startswith("task-sdr=")] == ["0.2.2", "0.2.1", "0.2.0", "0.1.0"]
    assert out[-1] == "S .config/task-sdr .local/share/task-sdr"      # user overlays/annotations are backed up


def test_i17_sqlite_check_mode_is_read_only_and_detects_corruption(env, tmp_path):
    db = env["db"]
    before = sorted((p.name, p.read_bytes()) for p in db.parent.iterdir())
    r = subprocess.run(["/usr/bin/python3", str(COMMON / "tools/sqlite_backup.py"), "--check", str(db)],
                       capture_output=True, text=True, env=env["env"])
    assert r.returncode == 0 and r.stdout.strip() == "snapshot ok"
    assert sorted((p.name, p.read_bytes()) for p in db.parent.iterdir()) == before
    live = sqlite3.connect(db)                        # writer active: -wal and -shm exist -> live mode=ro
    live.execute("INSERT INTO t VALUES(5)")
    live.commit()
    r = subprocess.run(["/usr/bin/python3", str(COMMON / "tools/sqlite_backup.py"), "--check", str(db)],
                       capture_output=True, text=True, env=env["env"])
    live.close()
    assert r.returncode == 0 and r.stdout.strip() == "live ok"
    bad = tmp_path / "bad.sqlite"
    bad.write_bytes(b"SQLite format 3\x00" + b"\xff" * 4000)
    r = subprocess.run(["/usr/bin/python3", str(COMMON / "tools/sqlite_backup.py"), "--check", str(bad)],
                       capture_output=True, text=True, env=env["env"])
    assert r.returncode == 1 and sorted(p.name for p in tmp_path.glob("bad*")) == ["bad.sqlite"]


# ------------------------------------------------------------------------------------------------------------
# HOST PLATFORM: hard requirement (directive 2026-10-14)
RPI_OS_64 = DEBIAN13                                   # 64-bit Raspberry Pi OS trixie reports Debian's os-release
RPI_OS_32 = ('PRETTY_NAME="Raspbian GNU/Linux 13 (trixie)"\nNAME="Raspbian GNU/Linux"\nVERSION_ID="13"\n'
             'VERSION="13 (trixie)"\nVERSION_CODENAME=trixie\nID=raspbian\nID_LIKE=debian\n')
OSR_REJECT = {
    "debian12": ('PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\nVERSION_ID="12"\nVERSION_CODENAME=bookworm\nID=debian\n',
                 "found ID=debian VERSION_ID=12 VERSION_CODENAME=bookworm"),
    "debian14": ('PRETTY_NAME="Debian GNU/Linux 14 (forky)"\nVERSION_ID="14"\nVERSION_CODENAME=forky\nID=debian\n',
                 "found ID=debian VERSION_ID=14 VERSION_CODENAME=forky"),
    "debian-testing-no-version": ('PRETTY_NAME="Debian GNU/Linux forky/sid"\nVERSION_CODENAME=forky\nID=debian\n',
                                  "VERSION_ID=<missing>"),
    "ubuntu2404": ('PRETTY_NAME="Ubuntu 24.04.1 LTS"\nNAME="Ubuntu"\nVERSION_ID="24.04"\nVERSION_CODENAME=noble\n'
                   'ID=ubuntu\nID_LIKE=debian\n', "found ID=ubuntu VERSION_ID=24.04 VERSION_CODENAME=noble"),
    "fedora": ('NAME="Fedora Linux"\nVERSION="40 (Workstation Edition)"\nID=fedora\nVERSION_ID=40\n', "found ID=fedora"),
    "raspbian32": (RPI_OS_32, "found ID=raspbian VERSION_ID=13 VERSION_CODENAME=trixie"),
    "id_like_only": ('ID=mydistro\nID_LIKE=debian\nVERSION_ID=13\nVERSION_CODENAME=trixie\n', "found ID=mydistro"),
    "debian13-wrong-codename": ('ID=debian\nVERSION_ID=13\nVERSION_CODENAME=bookworm\n', "VERSION_CODENAME=bookworm"),
    "no-codename": ('ID=debian\nVERSION_ID=13\n', "VERSION_CODENAME=<missing>"),
    "empty": ("", "is empty"),
    "garbage": ("this is not an os-release file\n", "line 1 is not a valid KEY=VALUE line"),
    "unterminated-quote": ('ID=debian\nVERSION_ID="13\nVERSION_CODENAME=trixie\n', "line 2 is not a valid KEY=VALUE line"),
    "command-substitution": ('ID=$(touch /tmp/task-pwned)\nVERSION_ID=13\nVERSION_CODENAME=trixie\n',
                             "line 1 is not a valid KEY=VALUE line"),
    "duplicate-id": ('ID=ubuntu\nID=debian\nVERSION_ID=13\nVERSION_CODENAME=trixie\n', "duplicate key ID"),
    "binary": ("\x00\x01\x02ELF\n", "not a valid KEY=VALUE line"),
    "missing": (None, "/etc/os-release does not exist"),
}
ARCH_REJECT = {"amd64": "found 'amd64'", "armhf": "found 'armhf'", "i386": "found 'i386'", "riscv64": "found 'riscv64'",
               "FAIL": "found '<nothing: dpkg --print-architecture failed>'"}


def set_osr(env, text):
    f = env["fx"] / "os-release"
    if text is None:
        f.unlink(missing_ok=True)
    else:
        f.write_text(text)


def snapshot(env):
    files = sorted(str(p.relative_to(env["home"])) for p in env["home"].rglob("*"))
    return files, env["state"].read_text(), env["db"].read_bytes()


def assert_rejected_cleanly(env, r, before, needle):
    assert r.returncode == 1, r.stdout + r.stderr
    assert "HOST REJECTED" in r.stdout and needle in r.stdout, r.stdout
    assert "expected" in r.stdout and "Why:" in r.stdout
    # nothing past the host check ran: no apt (not even -s), no sudo, no apt-mark, no backup, no file changes
    assert log(env) == "", log(env)
    assert "== apt simulation" not in r.stdout and "SHA256SUMS" not in r.stdout
    assert snapshot(env) == before
    assert not (env["home"] / "task-backups").exists()


@pytest.mark.parametrize("osr", [DEBIAN13, RPI_OS_64,
                                 "ID=debian\nVERSION_ID='13'\nVERSION_CODENAME=\"trixie\"\n# comment\n\n",
                                 DEBIAN13 + 'ID_LIKE=debian\nEXTRA="value with \\"escaped\\" quotes"\n'],
                         ids=["debian13", "rpi-os-64-trixie", "quoting-variants", "extra-keys"])
def test_i18_arm64_debian13_accepted(env, osr):
    set_osr(env, osr)
    for script, args, inp in (("preflight.sh", (), ""), ("install.sh", (), "")):
        r = run(env, script, *args, inp=inp)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "OK    host architecture: arm64" in r.stdout
        assert "OK    host OS: ID=debian VERSION_ID=13 VERSION_CODENAME=trixie" in r.stdout


@pytest.mark.parametrize("name", sorted(OSR_REJECT))
@pytest.mark.parametrize("script", ["preflight.sh", "install.sh --install", "rollback"])
def test_i19_bad_os_release_rejected_everywhere(env, name, script):
    text, needle = OSR_REJECT[name]
    before = snapshot(env)
    set_osr(env, text)
    if script == "rollback":                               # real backup from a real (fixture) install first
        set_osr(env, DEBIAN13)
        _, b = _install(env)
        env["log"].write_text("")
        before = snapshot(env)
        set_osr(env, text)
        r = run(env, str(b / "rollback.sh"), str(b), "--restore-data", inp="ROLLBACK test-demo-2.0\n")
        assert r.returncode == 1 and "HOST REJECTED" in r.stdout and needle in r.stdout, r.stdout
        assert log(env) == "" and snapshot(env) == before
        return
    r = run(env, *script.split(), inp="INSTALL test-demo-2.0\n")
    assert_rejected_cleanly(env, r, before, needle)
    assert not Path("/tmp/task-pwned").exists()


@pytest.mark.parametrize("arch", sorted(ARCH_REJECT))
@pytest.mark.parametrize("script", ["preflight.sh", "install.sh --install"])
def test_i20_wrong_architecture_rejected(env, arch, script):
    before = snapshot(env)
    r = run(env, *script.split(), inp="INSTALL test-demo-2.0\n", FAKE_ARCH=arch)
    assert_rejected_cleanly(env, r, before, ARCH_REJECT[arch])
    assert "expected 'arm64'" in r.stdout


def test_i21_preflight_and_install_agree(env):
    cases = [(DEBIAN13, "arm64")] + [(OSR_REJECT[k][0], "arm64") for k in ("debian12", "ubuntu2404", "garbage")] \
        + [(DEBIAN13, a) for a in ("amd64", "armhf")]
    for osr, arch in cases:
        set_osr(env, osr)
        p = run(env, "preflight.sh", FAKE_ARCH=arch)
        i = run(env, "install.sh", FAKE_ARCH=arch)           # check mode
        host = lambda out: [ln for ln in out.splitlines() if "host " in ln or "HOST REJECTED" in ln]
        assert host(p.stdout)[:2] == host(i.stdout)[:2], (osr, arch, p.stdout, i.stdout)
        assert (p.returncode == 0) == (i.returncode == 0), (osr, arch)


def test_i22_rollback_also_requires_host(env):
    _, b = _install(env)
    env["log"].write_text("")
    set_osr(env, OSR_REJECT["ubuntu2404"][0])
    r = run(env, str(b / "rollback.sh"), str(b), "--restore-data", inp="ROLLBACK test-demo-2.0\n")
    assert r.returncode == 1 and "HOST REJECTED" in r.stdout and log(env) == ""
    assert "task-demo 2.0" in env["state"].read_text()


BASHENV_ATTACK = r"""/usr/bin/dpkg() { echo arm64; }
tg_host_platform() { return 0; }
tg_require_host() { :; }
"""


@pytest.mark.parametrize("vector", ["old-test-vars", "path-fake-dpkg", "bash-env", "env-var", "exported-function",
                                    "ld-preload", "apt-config", "fixture-marker"])
@pytest.mark.parametrize("via_bash", [False, True], ids=["exec", "bash-script"])
def test_i23_env_bypass_attempts_on_a_REAL_run_are_rejected(env, tmp_path, vector, via_bash):
    """NO namespace here: the real scripts run on this real x86_64 build box (real /usr/bin/dpkg = amd64) with
    every bypass we can think of. All must be rejected as amd64 before anything else runs. (Safe: rejection
    happens before any apt call; install would need a typed phrase and sudo anyway.)"""
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    (fakebin / "dpkg").write_text("#!/bin/sh\necho arm64\n")
    (fakebin / "dpkg").chmod(0o755)
    good = tmp_path / "good-os-release"
    good.write_text(DEBIAN13)
    benv = tmp_path / "bashenv"
    benv.write_text(BASHENV_ATTACK)
    e = {"HOME": str(env["home"]), "PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}
    if vector == "old-test-vars":
        e.update(TASK_INSTALLER_TESTBIN=str(fakebin), TASK_OS_RELEASE=str(good))
    elif vector == "path-fake-dpkg":
        e["PATH"] = f"{fakebin}:/usr/sbin:/usr/bin:/sbin:/bin"
    elif vector == "bash-env":
        e.update(BASH_ENV=str(benv), ENV=str(benv))
    elif vector == "env-var":
        e.update(DPKG=str(fakebin / "dpkg"), OS_RELEASE=str(good), TG_REQ_ARCH="amd64", TG_FAIL="-100",
                 SHELLOPTS="xtrace", BASHOPTS="extdebug", tg_env_clean="1")
    elif vector == "exported-function":
        e["BASH_FUNC_tg_host_platform%%"] = "() { return 0; }"
        e["BASH_FUNC_tg_require_host%%"] = "() { :; }"
    elif vector == "ld-preload":
        e.update(LD_PRELOAD="/nonexistent/libfake.so", LD_LIBRARY_PATH=str(fakebin))
    elif vector == "apt-config":
        e.update(APT_CONFIG="/tmp/aptsim/apt.conf", DPKG_ADMINDIR=str(tmp_path), DPKG_ROOT=str(tmp_path))
    elif vector == "fixture-marker":
        for m in ("TEST-FIXTURE", ".task-test", "FIXTURE", "test-mode"):
            (env["rel"] / m).write_text("1")
    before = snapshot(env)
    for script, args in (("preflight.sh", ()), ("install.sh", ("--install",))):
        path = str(env["rel"] / script)
        cmd = ["/bin/bash", path, *args] if via_bash else [path, *args]
        r = subprocess.run(cmd, env=e, input="INSTALL test-demo-2.0\n", capture_output=True, text=True, timeout=120)
        assert r.returncode == 1, (vector, script, r.stdout, r.stderr)
        assert "HOST REJECTED" in r.stdout and "found 'amd64', expected 'arm64'" in r.stdout, (vector, r.stdout)
        assert "== apt simulation" not in r.stdout and "PREFLIGHT PASSED" not in r.stdout
    assert snapshot(env) == before and not (env["home"] / "task-backups").exists()


def test_i25_sdr_024_rollback_chain_and_settings():
    c = RELEASE / "corrections/sdr-0.2.4/release.conf"
    out = subprocess.run(["/bin/bash", "-c", '. "$1"; printf "%s\\n" "${ROLLBACK[@]}"; echo "S ${SETTINGS[*]}"; '
                          'echo "ID $REL_ID"; echo "T ${TARGETS[*]}"', "x", str(c)],
                         capture_output=True, text=True, check=True).stdout.splitlines()
    assert [ln.split("=")[1] for ln in out if ln.startswith("task-sdr=")] == ["0.2.3", "0.2.2", "0.2.1", "0.2.0",
                                                                             "0.1.0"]
    assert "S .config/task-sdr .local/share/task-sdr" in out and "ID phase4g-sdr-0.2.4" in out
    assert "T task-sdr=0.2.4" in out


@pytest.fixture
def sdr024(env):
    """The fixture rewired to the REAL sdr-0.2.4 release.conf and a Pi-like state (task-sdr 0.2.0 installed)."""
    rel = env["rel"]
    for f in list((rel / "debs").iterdir()) + list((rel / "rollback").iterdir()):
        f.unlink()
    shutil.copy2(RELEASE / "corrections/sdr-0.2.4/release.conf", rel / "release.conf")
    build_deb(rel / "debs/task-sdr_0.2.4_all.deb", "task-sdr", "0.2.4")
    names = ["debs/task-sdr_0.2.4_all.deb"]
    for v in ("0.2.3", "0.2.2", "0.2.1", "0.2.0", "0.1.0"):
        build_deb(rel / f"rollback/task-sdr_{v}_all.deb", "task-sdr", v)
        names.append(f"rollback/task-sdr_{v}_all.deb")
    (rel / "SHA256SUMS").write_text(subprocess.run(["/usr/bin/sha256sum", *names, "release.conf"], cwd=rel,
                                                   capture_output=True, text=True, check=True).stdout)
    env["state"].write_text("task-core 0.3.0\ntask-launcher 0.3.6\ntask-mesh 0.3.1\ntask-resources 0.2.3\n"
                            "python3-task-comms 0.3.1\ntask-sdr 0.2.0\n")
    env["sim"].write_text("Inst task-sdr [0.2.0] (0.2.4 local-deb [all])\nConf task-sdr (0.2.4 local-deb [all])\n")
    h = env["home"]
    (h / ".config/task-sdr").mkdir(parents=True)
    (h / ".config/task-sdr/prefs.json").write_text('{"freq_hz": 95500000, "mode": "WFM", "bookmarks": '
                                                   '[{"name": "A", "freq_hz": 95500000, "mode": "WFM"}]}')
    (h / ".local/share/task-sdr/overlays").mkdir(parents=True)
    (h / ".local/share/task-sdr/overlays/mine.json").write_text('{"x": 1}')
    old = h / "task-backups/phase4g-sdr-0.2.0-r3-20261024-124200"
    (old / "home").mkdir(parents=True)
    (old / "MANIFEST.txt").write_text("release phase4g-sdr-0.2.0-r3\n")
    env["old_backup"] = old
    return env


def test_i26_sdr_024_upgrade_from_020_backs_up_and_keeps_old_backup(sdr024):
    env = sdr024
    snap = {p.relative_to(env["old_backup"]): p.read_bytes() for p in env["old_backup"].rglob("*") if p.is_file()}
    r = run(env, "install.sh", "--install", inp="INSTALL phase4g-sdr-0.2.4\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "task-sdr 0.2.4" in env["state"].read_text()
    bs = [b for b in (env["home"] / "task-backups").iterdir() if b.name.startswith("phase4g-sdr-0.2.4-")]
    assert len(bs) == 1
    b = bs[0]
    assert (b / "versions-before.txt").read_text() == "task-sdr 0.2.0\n"
    assert (b / "rollback-plan.txt").read_text() == "task-sdr 0.2.0 task-sdr_0.2.0_all.deb\n"
    assert (b / "home/.config/task-sdr/prefs.json").is_file()
    assert (b / "home/.local/share/task-sdr/overlays/mine.json").read_text() == '{"x": 1}'
    for f in ("dpkg-query.tsv", "apt-mark-manual.txt", "apt-mark-auto.txt"):
        assert (b / "dpkg-state" / f).is_file()
    # the user's earlier backup is untouched
    assert {p.relative_to(env["old_backup"]): p.read_bytes() for p in env["old_backup"].rglob("*")
            if p.is_file()} == snap
    # other T.A.S.K. packages untouched
    st = env["state"].read_text()
    for pv in ("task-core 0.3.0", "task-launcher 0.3.6", "task-mesh 0.3.1", "task-resources 0.2.3",
               "python3-task-comms 0.3.1"):
        assert pv in st
    sudo = [ln for ln in log(env).splitlines() if ln.startswith("SUDO")]
    assert len(sudo) == 1 and "--no-remove" in sudo[0] and "task-sdr_0.2.4_all.deb" in sudo[0]


def test_i27_sdr_024_rollback_to_020_restores_config(sdr024):
    env = sdr024
    r = run(env, "install.sh", "--install", inp="INSTALL phase4g-sdr-0.2.4\n")
    assert r.returncode == 0, r.stdout
    b = next(b for b in (env["home"] / "task-backups").iterdir() if b.name.startswith("phase4g-sdr-0.2.4-"))
    before = (env["home"] / ".config/task-sdr/prefs.json").read_text()
    (env["home"] / ".config/task-sdr/prefs.json").write_text('{"changed by": "0.2.4"}')
    env["sim"].write_text("Inst task-sdr [0.2.4] (0.2.0 local-deb [all])\nConf task-sdr (0.2.0 local-deb [all])\n")
    r = run(env, str(b / "rollback.sh"), str(b), "--restore-data", inp="ROLLBACK phase4g-sdr-0.2.4\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "task-sdr 0.2.0" in env["state"].read_text()
    assert "rollback downgrade task-sdr 0.2.4 -> 0.2.0 (explicitly requested)" in r.stdout
    assert (env["home"] / ".config/task-sdr/prefs.json").read_text() == before
    aside = list((env["home"] / ".config").glob("task-sdr.pre-rollback-*"))
    assert len(aside) == 1 and "changed by" in (aside[0] / "prefs.json").read_text()
    assert (env["home"] / ".local/share/task-sdr/overlays/mine.json").read_text() == '{"x": 1}'
    last = [ln for ln in log(env).splitlines() if ln.startswith("SUDO")][-1]
    assert "--allow-downgrades" in last and "--no-remove" in last and "task-sdr_0.2.0_all.deb" in last


def test_i28_sdr_024_wrong_confirmation_and_remv_line_change_nothing(sdr024):
    env = sdr024
    r = run(env, "install.sh", "--install", inp="INSTALL phase4g-sdr-0.2.3\n")
    assert r.returncode == 1 and "task-sdr 0.2.0" in env["state"].read_text() and "SUDO" not in log(env)
    env["sim"].write_text("Inst task-sdr [0.2.0] (0.2.4 local-deb [all])\nRemv direwolf [1.7]\n")
    r = run(env, "install.sh", "--install", inp="INSTALL phase4g-sdr-0.2.4\n")
    assert r.returncode == 1 and "SUDO" not in log(env)
    assert not list((env["home"] / "task-backups").glob("phase4g-sdr-0.2.4-*"))
