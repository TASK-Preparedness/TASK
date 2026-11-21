# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4C client socket fallback: /run/task first, legacy /run/rain second."""

from task_core.socketpath import resolve_socket


def test_s01_order():
    have = set()
    ex = have.__contains__
    assert resolve_socket(environ={}, exists=ex) == "/run/task/core.sock"
    have.add("/run/rain/core.sock")
    assert resolve_socket(environ={}, exists=ex) == "/run/rain/core.sock"
    have.add("/run/task/core.sock")
    assert resolve_socket(environ={}, exists=ex) == "/run/task/core.sock"
    assert resolve_socket(environ={"TASK_CORE_SOCKET": "/x"}, exists=ex) == "/x"
    assert resolve_socket("/explicit", environ={"TASK_CORE_SOCKET": "/x"}, exists=ex) == "/explicit"
