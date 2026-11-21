# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Deterministic grid math for the home view (docs/platform/02-launcher-ui.md sections 4 and 4a).

This is a direct port of the planning calculators ``gridmath.py`` (Standard/Compact) and
``gridmath_large.py`` (Large), extended with the typography of each mode. The same function
drives the UI and the layout tests. All metric values are *logical* px; ``scale`` (the
launcher's UI scale setting, 1.0/1.25/1.5) multiplies them into Qt device-independent px.
Columns are never more than 3 (OD-L1).
"""

import math

STANDARD = dict(margin_top=40, margin_side=48, margin_bottom=16, header=96, gap_hg=32, gap_gf=24, footer=48,
                gutter_col=24, gutter_row=24, content_max=1200, minW=280, minH=120, maxH=200)
COMPACT = dict(margin_top=12, margin_side=16, margin_bottom=8, header=56, gap_hg=12, gap_gf=12, footer=36,
               gutter_col=12, gutter_row=12, content_max=1200, minW=220, minH=88, maxH=160)
LARGE = dict(margin_top=32, margin_side=64, margin_bottom=20, header=112, gap_hg=28, gap_gf=20, footer=56,
             gutter_col=32, gutter_row=24, content_max=1792, minW=480, minH=150, maxH=240)
LARGE_MIN_LOGICAL_W = 3 * LARGE["minW"] + 2 * LARGE["gutter_col"] + 2 * LARGE["margin_side"]  # 1632
COMPACT_BELOW_W = 1100
DENSE_BELOW_H = 150

# Typography and control sizes per effective mode (logical px).
TYPE = {
    "large": dict(title=60, title_line=72, subtitle=24, subtitle_line=32, chip_h=56, chip_text=18, chip_icon=28,
                  footer_text=18, dot=14, radius=18, icon=64, name=26, name_line=32, state=18, state_line=24,
                  icon_gap=12, focus_offset=6),
    "standard": dict(title=48, title_line=58, subtitle=20, subtitle_line=28, chip_h=48, chip_text=16, chip_icon=24,
                     footer_text=16, dot=12, radius=14, icon=56, name=20, name_line=28, state=16, state_line=22,
                     icon_gap=12, focus_offset=5),
    "compact": dict(title=28, title_line=40, subtitle=16, subtitle_line=22, chip_h=44, chip_text=16, chip_icon=22,
                    footer_text=16, dot=10, radius=12, icon=40, name=18, name_line=24, state=16, state_line=20,
                    icon_gap=14, focus_offset=4),
}

MODES = ("auto", "large", "standard", "compact")


def _fit(m, wl, hl, n, max_cols=3):
    content_w = min(m["content_max"], wl - 2 * m["margin_side"])
    grid_h = hl - m["margin_top"] - m["header"] - m["gap_hg"] - m["gap_gf"] - m["footer"] - m["margin_bottom"]
    cols = 1
    for c in (3, 2, 1):
        if c <= max_cols and content_w >= c * m["minW"] + (c - 1) * m["gutter_col"]:
            cols = c
            break
    rows = max(1, math.ceil(n / cols))
    tw = (content_w - (cols - 1) * m["gutter_col"]) / cols
    th_fit = (grid_h - (rows - 1) * m["gutter_row"]) / rows
    scroll = th_fit < m["minH"]
    th = max(m["minH"], min(m["maxH"], th_fit))
    return dict(cols=cols, rows=rows, tw=tw, th=th, th_fit=th_fit, scroll=scroll, grid_h=grid_h, content_w=content_w)


def _result(effective, reason, w, h, s, m, f):
    t = TYPE["compact" if effective == "compact" else effective]
    dense = effective == "standard" and f["th"] < DENSE_BELOW_H
    return dict(
        effective=effective, reason=reason, W=w, H=h, scale=s, logical=(round(w / s), round(h / s)),
        cols=f["cols"], rows=f["rows"], scroll=f["scroll"], dense=dense, compact=effective == "compact",
        tile_logical=(math.floor(f["tw"]), math.floor(f["th"])),
        tile=(math.floor(f["tw"] * s), math.floor(f["th"] * s)),
        content_w_logical=round(f["content_w"]), content_w=math.floor(f["content_w"] * s),
        grid_h_logical=round(f["grid_h"]), m=m, t=t,
        px={k: round(v * s) for k, v in m.items()},
        tp={k: round(v * s) for k, v in t.items()},
    )


def standard_layout(w, h, s, n=12, force_compact=False):
    wl, hl = w / s, h / s
    if not force_compact and wl >= COMPACT_BELOW_W:
        full = _fit(STANDARD, wl, hl, n)
        if not full["scroll"]:
            return _result("standard", "", w, h, s, STANDARD, full)
        reason = f"tile height {full['th_fit']:.1f} < {STANDARD['minH']} (Standard would scroll)"
    elif force_compact:
        reason = "Compact selected"
    else:
        reason = f"window {round(wl)} logical px < {COMPACT_BELOW_W}"
    return _result("compact", reason, w, h, s, COMPACT, _fit(COMPACT, wl, hl, n))


def layout(w, h, s=1.0, mode="auto", n=12):
    """Return the effective layout. ``mode``: auto (= Large, the approved default, OD-L10) | large |
    standard | compact. Large falls back to Standard, which falls back to Compact and then scrolling."""
    if mode not in MODES:
        mode = "auto"
    s = float(s) if s and s > 0 else 1.0
    wl, hl = w / s, h / s
    if mode in ("auto", "large"):
        m = LARGE
        f = _fit(m, wl, hl, n)
        if wl >= LARGE_MIN_LOGICAL_W and f["cols"] == 3 and f["th_fit"] >= m["minH"]:
            f["th"] = min(m["maxH"], f["th_fit"])
            f["scroll"] = False
            return _result("large", "", w, h, s, m, f)
        why = (f"window {round(wl)} logical px is narrower than {LARGE_MIN_LOGICAL_W}" if wl < LARGE_MIN_LOGICAL_W
               else f"tile height {f['th_fit']:.1f} < {m['minH']}")
        r = standard_layout(w, h, s, n)
        r["reason"] = why + ("" if r["effective"] == "standard" else "; " + (r["reason"] or ""))
        return r
    if mode == "compact":
        return standard_layout(w, h, s, n, force_compact=True)
    return standard_layout(w, h, s, n)


def describe(requested: str, result: dict) -> str:
    """Settings text, e.g. 'Layout: Large (requested) — using Standard: window 1536 ...'."""
    names = {"auto": "Automatic (Large)", "large": "Large", "standard": "Standard", "compact": "Compact"}
    eff = result["effective"].capitalize()
    req = names.get(requested, requested)
    target = {"auto": "large"}.get(requested, requested)
    if result["effective"] == target:
        return f"Layout: {req} — in use"
    return f"Layout: {req} (requested) — using {eff}: {result['reason']}"
