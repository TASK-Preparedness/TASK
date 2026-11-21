# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Weather resources: honest, offline-first status and a small data-source interface.

Nothing here downloads or forecasts. A source reports what is installed and which local products
exist with their age. "Forecast" is never claimed; the newest local product is shown with its age.

Data-source interface (for future satellite / radio / cached products)::

    class WeatherSource:
        id: str            # "noaa-apt", "satdump", "rtl_433", "dir:<path>", ...
        name: str
        def detect(self) -> SourceStatus           # installed? data dirs? (fast, no network)
        def products(self, limit=50) -> list[Product]   # local files only, newest first

A Product is (kind, title, path, mtime). Kinds: "satellite-image", "sensor-log", "aprs-wx",
"text-bulletin", "other". Future sources (task-core ``weather.products`` capability, APRS weather
from the receive-only monitor, cached GRIB files) implement the same two methods.
"""

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from task_launcher.services import probe

# Known receive/decode tools: (program, description, product kind). Detected only if present.
TOOLS = (
    ("noaa-apt", "NOAA APT satellite image decoder", "satellite-image"),
    ("satdump", "SatDump satellite decoder", "satellite-image"),
    ("wxtoimg", "WXtoImg APT decoder", "satellite-image"),
    ("aptdec", "aptdec APT decoder", "satellite-image"),
    ("rtl_433", "rtl_433 ISM-band sensor decoder (weather stations)", "sensor-log"),
    ("acarsdec", "acarsdec ACARS decoder (aviation messages, may carry weather)", "text-bulletin"),
    ("dumpvdl2", "dumpvdl2 VDL2 decoder (aviation messages)", "text-bulletin"),
)
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
LOG_EXT = {".json", ".jsonl", ".csv", ".log", ".txt"}


@dataclass
class Product:
    kind: str
    title: str
    path: str
    mtime: float

    def age(self, now=None):
        return probe.file_age_text(self.mtime, now)


@dataclass
class SourceStatus:
    id: str
    name: str
    installed: bool
    path: str = ""
    detail: str = ""


class WeatherSource:
    id = "base"
    name = "base"

    def detect(self) -> SourceStatus:  # pragma: no cover - interface
        raise NotImplementedError

    def products(self, limit=50):
        return []


class ToolSource(WeatherSource):
    def __init__(self, program, description, kind, finder=probe.find_program):
        self.id, self.name, self.kind = program, description, kind
        self.path = finder([program]).get(program, "")

    def detect(self):
        return SourceStatus(self.id, self.name, bool(self.path), self.path,
                            "installed" if self.path else "not installed")


class DirSource(WeatherSource):
    """A local folder of decoded products (configured in reference.toml [weather] dirs)."""

    def __init__(self, path):
        self.id, self.name, self.dir = f"dir:{path}", f"Local folder {path}", Path(path)

    def detect(self):
        ok = self.dir.is_dir()
        return SourceStatus(self.id, self.name, ok, str(self.dir), "folder present" if ok else "folder missing")

    def products(self, limit=50):
        found = []
        try:
            with os.scandir(self.dir) as it:
                for i, e in enumerate(it):
                    if i > 5000:
                        break
                    if not e.is_file(follow_symlinks=False):
                        continue
                    ext = os.path.splitext(e.name)[1].lower()
                    kind = "satellite-image" if ext in IMAGE_EXT else "sensor-log" if ext in LOG_EXT else None
                    if kind:
                        found.append(Product(kind, e.name, e.path, e.stat(follow_symlinks=False).st_mtime))
        except OSError:
            return []
        found.sort(key=lambda p: p.mtime, reverse=True)
        return found[:limit]


@dataclass
class WeatherStatus:
    tools: list = field(default_factory=list)       # SourceStatus
    dirs: list = field(default_factory=list)        # (SourceStatus, [Product])
    core_capability: str = None                     # task-core weather.products status (if known)
    config_error: str = ""
    checked: float = 0.0

    @property
    def newest(self):
        prods = [p for _, ps in self.dirs for p in ps]
        return max(prods, key=lambda p: p.mtime) if prods else None

    def summary(self, now=None):
        n_tools = sum(1 for t in self.tools if t.installed)
        newest = self.newest
        if newest:
            return f"Local weather data · newest {newest.age(now)} · no forecast"
        if n_tools:
            return f"{n_tools} weather decoder{'s' if n_tools != 1 else ''} installed · no local data"
        return "No weather sources or local data · no forecast"


def collect(ref_dirs=(), finder=probe.find_program, now=time.time):
    st = WeatherStatus(checked=now())
    for prog, desc, kind in TOOLS:
        st.tools.append(ToolSource(prog, desc, kind, finder).detect())
    for d in ref_dirs:
        src = DirSource(d)
        status = src.detect()
        st.dirs.append((status, src.products() if status.installed else []))
    return st
