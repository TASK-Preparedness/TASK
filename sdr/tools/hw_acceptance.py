#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-sdr 0.2.4 HARDWARE ACCEPTANCE (RTL-SDR Blog V4 + Pi, RECEIVE ONLY). Run as the desktop user, never root.

  hw_acceptance.py run [--minutes 5.5] [--freq-mhz 95.5] [--out DIR]
      Guided: starts SDR Studio with --diag-log, you press Start and tune a STRONG WFM station; it records
      RMS/peak/AGC/underruns/overruns/IQ rate/DSP time/latency once per second for >= 5 minutes, then guides a
      Smart Scanner check (scan -> stop -> receive audio returns) and a clean close + restart. Writes a report.
  hw_acceptance.py analyze DIAG.jsonl [--steady-from S]
      Offline PASS/FAIL evaluation of a diagnostics log (also used by `run`).

It never transmits, never changes audio configuration (no pactl/wpctl/amixer), never touches Direwolf, and
starts nothing at login. Diagnostics are plain JSON lines in a file you choose (default ~/task-sdr-acceptance-*)."""
import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

# Acceptance thresholds (documented in INSTALL.md / TEST-REPORT.md)
TH = {"iq_rate_ratio_min": 0.995,       # samples actually delivered by the dongle vs. nominal 1.024 MSPS
      "iq_dropped_blocks_max": 0,       # reader->DSP queue overflow
      "underrun_events_per_min_max": 0.5,  # after the first 10 s
      "overrun_events_max": 0,
      "rms_dbfs_range": (-26.0, -8.0),  # programme audio level after AGC/volume (volume 1.0 recommended)
      "peak_dbfs_max": -0.1,            # never full scale
      "clipped_samples_max": 0,
      "dsp_over_budget_max": 0,
      "queue_ms_max": 500.0}


def load(path):
    rows = []
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(ln))
        except ValueError:
            pass
    return rows


def analyze(rows, steady_from=10.0):
    """-> (verdict 'PASS'/'FAIL'/'INSUFFICIENT', list of (check, value, limit, ok)). Uses only receiving rows."""
    rx = [r for r in rows if r.get("state") == "connected" and r.get("mode")]
    out = []
    if len(rx) < 2:
        return "INSUFFICIENT", [("connected rows", len(rx), ">= 2", False)]
    t0 = rx[0]["t"]
    steady = [r for r in rx if r["t"] - t0 >= steady_from] or rx
    dur = steady[-1]["t"] - steady[0]["t"]
    out.append(("steady duration s", round(dur, 1), ">= 300 (5 min)", dur >= 300))
    ratios = [r["iq_rate_ratio"] for r in steady if r.get("iq_rate_ratio")]
    med = statistics.median(ratios) if ratios else 0.0
    out.append(("IQ rate ratio (median)", round(med, 4), f">= {TH['iq_rate_ratio_min']}", med >= TH["iq_rate_ratio_min"]))
    out.append(("IQ rate ratio (min)", round(min(ratios), 4) if ratios else None, "info", True))

    def delta(k):
        return (steady[-1].get(k) or 0) - (steady[0].get(k) or 0)
    out.append(("IQ dropped blocks", delta("iq_dropped_blocks"), f"<= {TH['iq_dropped_blocks_max']}",
                delta("iq_dropped_blocks") <= TH["iq_dropped_blocks_max"]))
    out.append(("read errors", delta("read_errors"), "0", delta("read_errors") == 0))
    upm = delta("audio_underrun_events") / max(dur / 60, 1e-9)
    out.append(("audio underrun events / min", round(upm, 2), f"<= {TH['underrun_events_per_min_max']}",
                upm <= TH["underrun_events_per_min_max"]))
    out.append(("audio underrun samples", delta("audio_underrun_samples"), "info", True))
    out.append(("audio overrun events", delta("audio_overrun_events"), f"<= {TH['overrun_events_max']}",
                delta("audio_overrun_events") <= TH["overrun_events_max"]))
    rms = [r["audio_rms_dbfs"] for r in steady if r.get("audio_rms_dbfs", -200) > -100]
    lo, hi = TH["rms_dbfs_range"]
    m = statistics.median(rms) if rms else -200.0
    out.append(("audio RMS dBFS (median)", round(m, 1), f"{lo} .. {hi}", lo <= m <= hi))
    pk = max((r.get("audio_peak_dbfs", -200) for r in steady), default=-200)
    out.append(("audio peak dBFS (max)", pk, f"<= {TH['peak_dbfs_max']}", pk <= TH["peak_dbfs_max"]))
    out.append(("clipped samples", delta("clipped_samples"), "0", delta("clipped_samples") <= TH["clipped_samples_max"]))
    ag = [r["agc_gain_db"] for r in steady if "agc_gain_db" in r]
    out.append(("AGC gain dB min/median/max", (min(ag), round(statistics.median(ag), 1), max(ag)) if ag else None,
                "info", True))
    dm = max((r.get("dsp_max_ms") or 0) for r in steady)
    budget = steady[-1].get("dsp_budget_ms") or 64.0
    out.append(("DSP max ms per block", dm, f"< budget {budget}", dm < budget))
    out.append(("DSP avg ms per block", steady[-1].get("dsp_avg_ms"), "info", True))
    out.append(("DSP over budget", delta("dsp_over_budget"), "0", delta("dsp_over_budget") <= TH["dsp_over_budget_max"]))
    q = max((r.get("audio_queue_ms") or 0) for r in steady)
    out.append(("audio queue ms (max) = app-side latency", q, f"<= {TH['queue_ms_max']}", q <= TH["queue_ms_max"]))
    for k in ("sink_mode", "sink_buffer_bytes", "sink_partial_writes", "sink_buffer_ms", "latency_ms_est", "sink_restarts",
              "sink_idle_events", "sink_sink_errors", "sink_last_error"):
        if k in steady[-1]:
            out.append((k, steady[-1][k], "info", True))
    verdict = "PASS" if all(ok for *_, ok in out) else "FAIL"
    return verdict, out


def report(verdict, checks):
    lines = [f"{'check':44} {'value':>24}  limit", "-" * 90]
    for name, val, lim, ok in checks:
        lines.append(f"{name:44} {str(val):>24}  {lim}{'' if ok else '   <-- FAIL'}")
    lines.append(f"VERDICT (automatic part): {verdict}")
    return "\n".join(lines)


def ask(q):
    try:
        return input(f"{q} [y/n] ").strip().lower().startswith("y")
    except EOFError:
        return False


def wait_enter(msg):
    try:
        input(f"{msg}  (press Enter) ")
    except EOFError:
        pass


def gui_env():
    e = dict(os.environ)
    uid = os.getuid()
    e.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")          # PipeWire/Wayland sockets of the desktop session
    if "WAYLAND_DISPLAY" not in e and "DISPLAY" not in e:
        rt = Path(e["XDG_RUNTIME_DIR"])
        w = sorted(rt.glob("wayland-[0-9]"))
        if w:
            e["WAYLAND_DISPLAY"] = w[0].name
        else:
            e["DISPLAY"] = ":0"
    return e


def launch(diag, extra=()):
    exe = "/usr/bin/task-sdr"
    return subprocess.Popen([exe, "--diag-log", str(diag), *extra], env=gui_env(), stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=open(str(diag) + ".stderr", "w"))


def tail_status(diag):
    rows = load(diag) if Path(diag).exists() else []
    if not rows:
        return "no diagnostics yet (press Start in SDR Studio)"
    r = rows[-1]
    return (f"{r.get('state')} {r.get('freq_hz', 0) / 1e6:.3f} MHz {r.get('mode')} rms {r.get('audio_rms_dbfs')} dBFS "
            f"peak {r.get('audio_peak_dbfs')} agc {r.get('agc_gain_db')} dB iq {r.get('iq_rate_ratio')} "
            f"under {r.get('audio_underrun_events')} over {r.get('audio_overrun_events')} q {r.get('audio_queue_ms')} ms")


def close_app(p, timeout=20):
    wait_enter("Close SDR Studio normally (window close button)")
    try:
        rc = p.wait(timeout)
    except subprocess.TimeoutExpired:
        print("SDR Studio did not exit within 20 s -> terminating it (counts as FAIL)")
        p.terminate()
        p.wait(10)
        return False
    return rc == 0


def run(a):
    if os.geteuid() == 0:
        print("Run as the desktop user, not root.")
        return 2
    out = Path(a.out or Path.home() / f"task-sdr-acceptance-{time.strftime('%Y%m%d-%H%M%S')}")
    out.mkdir(parents=True, exist_ok=True)
    ver = subprocess.run(["/usr/bin/dpkg-query", "-W", "-f", "${Version}", "task-sdr"], capture_output=True,
                         text=True).stdout.strip()
    print(f"task-sdr installed: {ver or 'NOT INSTALLED'}   output: {out}")
    if ver != "0.2.4":
        print("Expected task-sdr 0.2.4. Stop.")
        return 1
    diag = out / "diag-receive.jsonl"
    print(f"\n1) RECEIVE {a.minutes} min. In SDR Studio: select RTL-SDR, press Start, tune {a.freq_mhz} MHz WFM, "
          "AGC on, volume 100% (set the speaker level with the desktop volume, not in the app).")
    p = launch(diag)
    wait_enter("When audio plays from the station")
    t_end = time.time() + a.minutes * 60
    while time.time() < t_end:
        print(f"  [{int(t_end - time.time()):4d} s left] {tail_status(diag)}", flush=True)
        time.sleep(15)
    manual = {"audio continuous (no chop) for the whole run": ask("Was the audio continuous the whole time?"),
              "level comparable to SDR++/GQRX at the same station": ask("Loud enough (similar to SDR++/GQRX)?"),
              "no distortion": ask("Free of distortion/clipping?")}
    print("\n2) SCANNER: open the Scanner tab, start a scan (e.g. 144-148 MHz) for ~30 s, then STOP it, and tune back to "
          f"{a.freq_mhz} MHz WFM.")
    wait_enter("When you have tuned back and hear the station again")
    mark = load(diag)[-1] if load(diag) else {}
    time.sleep(15)
    after = load(diag)[-1] if load(diag) else {}
    gen = (after.get("audio_generated") or 0) - (mark.get("audio_generated") or 0)
    manual["audio returned after scanner stop"] = ask("Did the station audio return after stopping the scan?")
    scan_ok = gen >= 0.8 * 15 * 48000 and after.get("mode") == "WFM"
    clean1 = close_app(p)
    print("\n3) RESTART: SDR Studio starts again; press Start; check the station plays, then close it.")
    diag2 = out / "diag-restart.jsonl"
    p2 = launch(diag2)
    wait_enter("When audio plays again (or if it does not)")
    time.sleep(10)
    manual["audio after restart"] = ask("Audio OK after restart?")
    clean2 = close_app(p2)
    verdict, checks = analyze(load(diag))
    checks.append(("scanner -> receive: audio samples generated in 15 s", gen, ">= 576000 and mode WFM", scan_ok))
    checks.append(("clean exit (1st run)", clean1, "True", clean1))
    checks.append(("clean exit (restart)", clean2, "True", clean2))
    r2 = [r for r in load(diag2) if r.get("state") == "connected"] if diag2.exists() else []
    checks.append(("restart: receiving rows", len(r2), ">= 5", len(r2) >= 5))
    for k, v in manual.items():
        checks.append((f"listener: {k}", v, "True", v))
    verdict = "PASS" if all(ok for *_, ok in checks) else "FAIL"
    txt = report(verdict, checks)
    (out / "REPORT.txt").write_text(f"task-sdr {ver} hardware acceptance {time.strftime('%F %T %Z')}\n{txt}\n")
    print("\n" + txt + f"\n\nSaved: {out}/REPORT.txt  (send this folder back)")
    return 0 if verdict == "PASS" else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hw_acceptance.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--minutes", type=float, default=5.5)
    r.add_argument("--freq-mhz", default="95.5")
    r.add_argument("--out")
    z = sub.add_parser("analyze")
    z.add_argument("log")
    z.add_argument("--steady-from", type=float, default=10.0)
    a = ap.parse_args(argv)
    if a.cmd == "run":
        if a.minutes < 5:
            print("--minutes must be >= 5")
            return 2
        return run(a)
    verdict, checks = analyze(load(a.log), a.steady_from)
    print(report(verdict, checks))
    return {"PASS": 0, "FAIL": 1}.get(verdict, 3)


if __name__ == "__main__":
    sys.exit(main())
