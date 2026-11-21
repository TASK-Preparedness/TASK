# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Contract future data-source plugins (gpsd, APRS, additional radios) will implement.

No plugin loader exists in v0.1.0; this module only fixes the shape so later versions do not
need to change the core. Nothing imports it at runtime.
"""

from __future__ import annotations

from typing import Iterable, Protocol

from task_mesh.domain.geo import GeoEntity


class DataSourcePlugin(Protocol):
    plugin_id: str
    display_name: str

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def entities(self) -> Iterable[GeoEntity]: ...
