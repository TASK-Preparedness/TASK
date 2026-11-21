# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Persistent preferences and presets (~/.config/task-sdr/prefs.json, 0600). Never system paths."""

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from task_comms import paths

from task_sdr.dsp import MODES
from task_sdr.freq import ABS_MAX_HZ, FrequencyError, hz as _hz, is_hz

DEFAULT_PRESETS = [
    {"name": "NOAA WX 162.550", "freq_hz": 162_550_000, "mode": "NFM"},
    {"name": "NOAA WX 162.400", "freq_hz": 162_400_000, "mode": "NFM"},
    {"name": "APRS 144.390 (listen)", "freq_hz": 144_390_000, "mode": "NFM"},
    {"name": "Airband 121.500", "freq_hz": 121_500_000, "mode": "AM"},
]
MIN_HZ, MAX_HZ = 500_000, 1_766_000_000      # RTL-SDR Blog V4 advertised tuning range (HF via upconverter)


@dataclass
class Prefs:
    freq_hz: int = 162_550_000
    mode: str = "NFM"
    gain_db: float = None         # None = automatic
    ppm: int = 0
    sample_rate: int = 1_024_000
    squelch_dbfs: float = None
    volume: float = 0.5
    audio_device: str = ""        # QAudioDevice id; never the Direwolf card
    presets: list = field(default_factory=lambda: [dict(p) for p in DEFAULT_PRESETS])
    # SDR Studio (0.2.0)
    bandwidth_hz: int = None      # None = mode default (task_sdr.dsp.BANDWIDTH)
    agc: bool = True              # audio AGC
    backend: str = "rtlsdr"       # rtlsdr | soapy | simulated
    device_index: int = 0
    s9_dbfs: float = -30.0        # S-meter reference (uncalibrated)
    bookmarks: list = field(default_factory=list)   # [{name, freq_hz, mode, bandwidth_hz}]
    # Smart Scanner (0.2.1)
    scan_start_hz: int = 144_000_000
    scan_stop_hz: int = 148_000_000
    scan_step_hz: int = 12_500
    scan_mode: str = "NFM"
    scan_snr_db: float = 10.0
    scan_vad: bool = True
    scan_ignores: list = field(default_factory=list)  # 0.2.1 format: persistent ignore frequencies (Hz).
    #                                                  0.2.2 keeps writing it so a rollback to 0.2.1 keeps them.
    # 0.2.2
    scan_ignore_entries: list = field(default_factory=list)  # [{freq_hz, tolerance_hz, label}] persistent only
    scan_ignore_tol_hz: int = 0                                # default tolerance for new ignores (0 = exact)
    scan_carrier_timeout_s: float = None                       # OFF by default

    def validate(self):
        """Every Hz field must be an exact integer (no float/str/bool/NaN/inf) inside its bounds."""
        if self.mode not in MODES:
            raise ValueError("unknown mode")
        _hz(self.freq_hz, "frequency", MIN_HZ, MAX_HZ)
        if self.bandwidth_hz is not None:
            _hz(self.bandwidth_hz, "bandwidth", 100, 250_000)
        _hz(self.sample_rate, "sample rate", 1, 100_000_000)
        if not isinstance(self.bookmarks, list) or not all(valid_entry(b) for b in self.bookmarks):
            raise ValueError("bad bookmarks")
        if not isinstance(self.presets, list) or not all(valid_entry(b) for b in self.presets):
            raise ValueError("bad presets")
        if self.scan_mode not in MODES:
            raise ValueError("bad scan settings")
        _hz(self.scan_step_hz, "scan step", 1, 10_000_000)
        _hz(self.scan_start_hz, "scan start")
        _hz(self.scan_stop_hz, "scan stop")
        if not isinstance(self.scan_ignores, list) or not all(is_hz(f) for f in self.scan_ignores):
            raise ValueError("bad scan ignore list")
        if not isinstance(self.scan_ignore_entries, list) or not all(valid_ignore(e) for e in self.scan_ignore_entries):
            raise ValueError("bad scan ignore entries")
        _hz(self.scan_ignore_tol_hz, "ignore tolerance", 0, 1_000_000)
        if self.scan_carrier_timeout_s is not None and not 1 <= float(self.scan_carrier_timeout_s) <= 3600:
            raise ValueError("carrier timeout must be 1-3600 s or off")
        if isinstance(self.ppm, bool) or not isinstance(self.ppm, int) or not -100 <= self.ppm <= 100:
            raise ValueError("PPM must be -100..100")
        return self


def valid_entry(e):
    """Bookmark/preset: {name: str, freq_hz: int Hz, mode?: known mode, bandwidth_hz?: int or None}."""
    return (isinstance(e, dict) and isinstance(e.get("name", ""), str) and len(e.get("name", "")) <= 200
            and is_hz(e.get("freq_hz")) and e.get("mode", "NFM") in MODES
            and (e.get("bandwidth_hz") is None or is_hz(e.get("bandwidth_hz"), 100, 250_000)))


def valid_ignore(e):
    return (isinstance(e, dict) and is_hz(e.get("freq_hz")) and is_hz(e.get("tolerance_hz", 0), 0, 1_000_000)
            and isinstance(e.get("label", ""), str))


_LIST_CHECKS = {"bookmarks": valid_entry, "presets": valid_entry, "scan_ignore_entries": valid_ignore,
                "scan_ignores": is_hz}


def ignore_list(prefs):
    """Persistent ignores for the Scanner: 0.2.2 entries plus any 0.2.1 plain frequencies not covered by an
    entry (migrated losslessly as EXACT, 0 Hz, ignores). Nothing is dropped."""
    have = {e["freq_hz"] for e in prefs.scan_ignore_entries}
    return list(prefs.scan_ignore_entries) + [f for f in prefs.scan_ignores if f not in have]


def store_ignores(prefs, ignore_list_obj):
    prefs.scan_ignore_entries, prefs.scan_ignores = ignore_list_obj.to_prefs()


def path():
    return paths.config_dir("task-sdr") / "prefs.json"


def load(p=None) -> Prefs:
    p = Path(p) if p else path()
    try:
        data = json.loads(p.read_text())
        names = {f.name for f in fields(Prefs)}
        if not isinstance(data, dict):
            return Prefs()
        data = {k: v for k, v in data.items() if k in names}
        for k, ok in _LIST_CHECKS.items():          # drop only the bad entries; keep the user's good ones
            if isinstance(data.get(k), list):
                data[k] = [e for e in data[k] if ok(e)]
        return Prefs(**data).validate()
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        return Prefs()


def save(prefs: Prefs, p=None):
    prefs.validate()
    p = Path(p) if p else path()
    paths.private_dir(p.parent)
    tmp = p.with_name(f".prefs.{os.getpid()}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(asdict(prefs), f, indent=1)
    os.replace(tmp, p)
