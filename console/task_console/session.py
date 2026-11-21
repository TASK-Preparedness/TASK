# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Session vocabulary shared by the controller and the dialogs (PHASE-2.md sections 6.3-6.5).

The token itself lives only in CoreClient memory; nothing here stores it.
"""

import re

ROLES = ("public", "operator", "administrator")
MAX_PASSWORD = 256  # code points (D4); the console counts the field text and sends it unchanged

MSG_RESTARTED = "task-core restarted \u2014 please sign in again"
MSG_EXPIRED = "Session expired \u2014 please sign in again"
MSG_TOO_LONG = "Passwords are at most 256 characters"
MSG_UNAVAILABLE = "task-core unavailable"


def rank(role: str) -> int:
    return ROLES.index(role) if role in ROLES else 0


def at_least(role: str, minimum: str) -> bool:
    return rank(role) >= rank(minimum)


def retry_seconds(message: str):
    """'too many attempts, retry in 30 s' -> 30 (None if the server gave no number)."""
    match = re.search(r"retry in (\d+) s", message or "")
    return int(match.group(1)) if match else None


def password_too_long(text: str) -> bool:
    return len(text) > MAX_PASSWORD
