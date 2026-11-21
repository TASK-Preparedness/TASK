#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""OBSERVED apt simulations on the build box using a PRIVATE arm64 apt state (APT_CONFIG; real Debian 13 trixie,
trixie-updates and trixie-security package lists for arm64). This is NOT a Raspberry Pi and installs nothing.
For each scenario a dpkg status file is synthesised to represent "already installed": the closure apt itself
computes for the prior T.A.S.K. debs on an empty system (control data from the real debs and the real trixie
records). Then the release's own guard check (task-guard.sh tg_apt_sim) runs against real apt-get -s.
usage: aptsim_scenarios.py POOL_DIR OUT_DIR SCENARIO_FILE(json)"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

BASECONF = "/tmp/aptsim/apt.conf"
GUARD = Path(__file__).resolve().parents[1] / "common/task-guard.sh"


def conf(tmp, status):
    p = tmp / "apt.conf"
    p.write_text(f'#include "{BASECONF}";\nDir::State::status "{status}";\n')
    return p


def apt(cfg, *args):
    env = dict(os.environ, APT_CONFIG=str(cfg), LC_ALL="C")
    return subprocess.run(["/usr/bin/apt-get", *args], env=env, capture_output=True, text=True)


DROP = re.compile(r"(Filename|Size|MD5sum|SHA256|Description-md5|Tag|Installed-Size):")


def clean(stanza):
    """Status stanza from a control/Packages stanza: drop archive-only fields INCLUDING their continuation
    lines, add the installed status."""
    keep, skip = [], False
    for ln in stanza.splitlines():
        if not ln.strip():
            continue
        if ln[0] in " \t":
            if not skip:
                keep.append(ln)
            continue
        skip = bool(DROP.match(ln))
        if not skip:
            keep.append(ln)
    keep.insert(1, "Status: install ok installed")
    return "\n".join(keep) + "\n\n"


def records(cfg, wanted, local):
    out = []
    archive = [f"{p}={v}" for p, v in wanted if (p, v) not in local]
    by = {}
    if archive:
        env = dict(os.environ, APT_CONFIG=str(cfg), LC_ALL="C")
        txt = subprocess.run(["/usr/bin/apt-cache", "show", "--no-all-versions", *archive], env=env,
                             capture_output=True, text=True, check=True).stdout
        for st in txt.split("\n\n"):
            f = dict(re.findall(r"^(Package|Version): (.*)$", st, re.M))
            if f:
                by.setdefault((f["Package"], f["Version"]), st)
    for key in wanted:
        if key in local:
            st = subprocess.run(["/usr/bin/dpkg-deb", "-f", local[key]], capture_output=True, text=True,
                                check=True).stdout
        else:
            st = by[key]
        out.append(clean(st))
    return out


def make_state(tmp, base_debs):
    status = tmp / "status"
    status.write_text("")
    if not base_debs:
        return status
    cfg = conf(tmp, status)
    r = apt(cfg, "-s", "-o", "Debug::NoLocking=1", "install", "--no-remove", *base_debs)
    if r.returncode != 0:
        raise SystemExit(f"base state not installable: {r.stdout}{r.stderr}")
    local = {}
    for d in base_debs:
        f = subprocess.run(["/usr/bin/dpkg-deb", "-f", d, "Package", "Version"], capture_output=True, text=True,
                           check=True).stdout
        local[(re.search(r"Package: (.*)", f).group(1), re.search(r"Version: (.*)", f).group(1))] = d
    wanted = re.findall(r"^Inst (\S+) (?:\[\S+\] )?\((\S+) ", r.stdout, re.M)
    recs = records(cfg, wanted, local)
    status.write_text("".join(recs))
    return status


def main():
    pool, out, scen = Path(sys.argv[1]), Path(sys.argv[2]), json.loads(Path(sys.argv[3]).read_text())
    out.mkdir(parents=True, exist_ok=True)
    summary = []
    for s in scen:
        tmp = out / ".work" / s["name"]
        tmp.mkdir(parents=True, exist_ok=True)
        status = make_state(tmp, [str(pool / d) for d in s["before"]])
        cfg = conf(tmp, status)
        debs = [str(pool / d) for d in s["install"]]
        script = ('. "$1"; shift; allow="$1"; shift; tg_apt_sim "$allow" "$@"; '
                  'printf "\\n--- raw apt-get -s output ---\\n%s\\n" "$TG_SIM_OUT"; '
                  'printf "RESULT fail=%s warn=%s\\n" "$TG_FAIL" "$TG_WARN"')
        env = dict(os.environ, APT_CONFIG=str(cfg), LC_ALL="C")
        r = subprocess.run(["/bin/bash", "-c", script, "sim", str(GUARD), " ".join(s.get("allow", [])), *debs],
                           env=env, capture_output=True, text=True)
        n_inst = len(re.findall(r"^Inst ", r.stdout, re.M))
        installed = []
        for st in status.read_text().split("\n\n"):
            f = dict(re.findall(r"^(Package|Version): (.*)$", st, re.M))
            if f and ("task" in f["Package"] or "rain" in f["Package"]):
                installed.append(f"{f['Package']} {f['Version']}")
        installed.sort()
        expect = s.get("expect", "pass")
        res = re.search(r"RESULT fail=(\d+) warn=(\d+)", r.stdout)
        verdict = "pass" if res and res.group(1) == "0" else "fail"
        ok = verdict == expect
        hdr = (f"OBSERVED SIMULATION (build box, private arm64 apt state, real trixie lists; NOT a Raspberry Pi)\n"
               f"Scenario: {s['name']}\n{s['desc']}\n"
               f"Installed before (T.A.S.K. packages; plus their resolved Debian dependencies): "
               f"{', '.join(installed) if installed else 'nothing (empty dpkg status)'}\n"
               f"Packages given to apt: {' '.join(s['install'])}\n"
               f"Guard verdict: {verdict.upper()} (expected {expect.upper()}) -> {'AS EXPECTED' if ok else 'UNEXPECTED'}\n"
               f"Inst lines: {n_inst}\n\n")
        (out / f"{s['name']}.txt").write_text(hdr + r.stdout + r.stderr)
        summary.append((s["name"], verdict, expect, ok, n_inst))
    with open(out / "SUMMARY.txt", "w") as f:
        f.write("OBSERVED apt -s simulations (private arm64 state on the x86 build box, real Debian 13 lists; NOT a Pi)\n")
        f.write(f"{'scenario':<42} {'verdict':<8} {'expected':<8} {'Inst':>4}  result\n")
        for n, v, e, ok, i in summary:
            f.write(f"{n:<42} {v:<8} {e:<8} {i:>4}  {'as expected' if ok else 'UNEXPECTED'}\n")
    print((out / "SUMMARY.txt").read_text())
    shutil_rm(out / ".work")
    sys.exit(0 if all(x[3] for x in summary) else 1)


def shutil_rm(p):
    import shutil
    shutil.rmtree(p, ignore_errors=True)


if __name__ == "__main__":
    main()
