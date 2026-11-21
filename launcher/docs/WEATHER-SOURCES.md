<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# Weather data-source interface (0.2.0)

Implementation: `task_launcher/services/weather.py`. The Weather window and the readiness line
only report **what is installed** and **which local products exist, with their age**. Nothing
is downloaded; nothing is called a forecast.

```python
class WeatherSource:
    id: str      # "noaa-apt", "rtl_433", "dir:/home/op/wx", later "core:weather.products"
    name: str
    def detect(self) -> SourceStatus          # fast, local, no network
    def products(self, limit=50) -> list[Product]   # newest first, local files only

@dataclass
class SourceStatus: id; name; installed: bool; path=""; detail=""

@dataclass
class Product: kind; title; path; mtime   # kind: satellite-image | sensor-log | aprs-wx |
                                          #       text-bulletin | other
```

Shipped sources: `ToolSource` (one per known decoder, detected in fixed directories, never on
`$PATH`), `DirSource` (a folder from `reference.toml`):

```toml
# ~/.config/task-launcher/reference.toml (optional; the launcher never creates it)
[weather]
dirs = ["/home/op/wx"]
[medical]
dirs = ["/home/op/Documents/medical"]
```

Planned sources (not implemented): rain-core `weather.products` provider (the capability exists
in rain-core and reports no provider today); APRS weather reports from the receive-only monitor
(`services/aprs.py` already parses them); cached GRIB files. Each will implement the same two
methods; any product shown must carry its timestamp and source.
