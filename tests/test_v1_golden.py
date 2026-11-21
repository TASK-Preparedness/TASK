# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""PHASE-2.md test 2: the v1 golden transcript recorded from 0.1.1 is replayed.

Normalized: event time, event id, uptime_seconds (section 17.1), and the
core.health "version" literal, which is 0.1.1 in the recording and must be the
running package version now (the same precedent as tests/test_not_root.py:19).
"""

import json
import sys
from pathlib import Path

import task_core

GOLDEN = Path(__file__).resolve().parent / "golden"


def _version_normalized(value):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key == "version" and item == "0.1.1" and "uptime_seconds" in value:
                item = task_core.__version__
            out[key] = _version_normalized(item)
        return out
    if isinstance(value, list):
        return [_version_normalized(item) for item in value]
    return value


def test_02_v1_golden_transcript_matches_0_1_1():
    sys.path.insert(0, str(GOLDEN))
    try:
        import v1_scenario
    finally:
        sys.path.remove(str(GOLDEN))
    recorded = json.loads((GOLDEN / "v1_transcript_0.1.1.json").read_text(encoding="utf-8"))
    assert recorded["recorded_with"] == "0.1.1"
    expected = _version_normalized(recorded["transcript"])
    actual = v1_scenario.run()
    assert len(actual) == len(expected)
    for index, (want, got) in enumerate(zip(expected, actual)):
        assert got == want, f"transcript entry {index} differs: {want.get('send', want.get('devices_json'))}"
