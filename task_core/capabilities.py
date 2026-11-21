# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Capability registry. Phase 1 registers no providers, so none are available."""

DEVICE_BACKED = {
    "gps.position": ("gps.primary",),
    "radio.rx": ("sdr.primary", "radio.primary"),
    "radio.tx": ("radio.primary",),
    "mesh.messaging": ("mesh.primary",),
    "mesh.position": ("mesh.primary",),
}
PROVIDER_ONLY = ("weather.products",)
ORDER = (
    "gps.position",
    "radio.rx",
    "radio.tx",
    "mesh.messaging",
    "mesh.position",
    "weather.products",
)


class Registry:
    def __init__(self, bus) -> None:
        self.bus = bus
        self.providers: set[str] = set()
        self.status: dict[str, str] = {}
        self._live = False

    def kind(self, name: str) -> str:
        if name in PROVIDER_ONLY:
            return "provider-only"
        return "device-backed"

    def recompute(self, connected_logicals: set[str]) -> dict[str, str]:
        updated: dict[str, str] = {}
        for name, logicals in DEVICE_BACKED.items():
            present = any(logical in connected_logicals for logical in logicals)
            if not present:
                updated[name] = "no-device"
            elif name in self.providers:
                updated[name] = "available"
            else:
                updated[name] = "no-provider"
        for name in PROVIDER_ONLY:
            if name in self.providers:
                updated[name] = "available"
            else:
                updated[name] = "no-provider"
        if self._live:
            for name in ORDER:
                if self.status.get(name) != updated[name]:
                    self.bus.publish(
                        "capability.changed",
                        "capabilities",
                        {
                            "name": name,
                            "kind": self.kind(name),
                            "status": updated[name],
                        },
                    )
        self.status = updated
        return updated

    def mark_live(self) -> None:
        self._live = True

    def public(self) -> dict:
        return {
            "capabilities": [
                {"name": name, "kind": self.kind(name), "status": self.status[name]}
                for name in ORDER
            ]
        }
