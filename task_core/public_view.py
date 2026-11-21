# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""D5 public view, enforced in task-core (PHASE-2.md section 5.6).

Public v2 clients get availability and counts only, never identifying device data.
"""

PUBLIC_EVENT_PREFIXES = ("core.", "module.", "capability.")
PUBLIC_EVENT_TOPICS = frozenset({"device.counts"})
ROLE_RANK = {"public": 0, "operator": 1, "administrator": 2}


def event_allowed(role: str, topic: str) -> bool:
    if ROLE_RANK.get(role, 0) >= ROLE_RANK["operator"]:
        return True
    return topic in PUBLIC_EVENT_TOPICS or topic.startswith(PUBLIC_EVENT_PREFIXES)


def filter_events(role: str, events: list) -> list:
    return [event for event in events if event_allowed(role, event["topic"])]


def redact_module_list(result: dict) -> dict:
    """Public module.list: every module without logical_devices, nothing else changed."""
    modules = []
    for module in result["modules"]:
        copy = {key: value for key, value in module.items() if key != "logical_devices"}
        modules.append(copy)
    return {"modules": modules}
