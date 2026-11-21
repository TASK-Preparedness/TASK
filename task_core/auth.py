# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import logging
from pathlib import Path

from task_core.config import read_toml

logger = logging.getLogger("task_core")

ROLES = ("public", "operator", "administrator")
RANK = {name: index for index, name in enumerate(ROLES)}


class Auth:
    """Maps a process uid to a role. This is not a browser session."""

    def __init__(self, mapping: dict[int, str]) -> None:
        self.mapping = mapping

    def role_for(self, uid: int) -> str:
        role = self.mapping.get(int(uid), "public")
        if role not in RANK:
            return "public"
        return role

    def allows(self, uid: int, minimum: str) -> bool:
        return RANK[self.role_for(uid)] >= RANK[minimum]


def load_auth(path: Path) -> Auth:
    if not path.is_file():
        logger.warning("auth file missing; all peers are public")
        return Auth({})
    try:
        document = read_toml(path.read_text(encoding="utf-8"))
    except Exception:
        logger.error("auth file rejected; all peers are public")
        return Auth({})
    peers = document.get("peers", {})
    if not isinstance(peers, dict):
        logger.error("auth file rejected; all peers are public")
        return Auth({})
    mapping: dict[int, str] = {}
    for key, value in peers.items():
        try:
            uid = int(str(key))
        except (TypeError, ValueError):
            logger.warning("ignored auth peer key")
            continue
        if value not in RANK:
            logger.warning("ignored auth peer role")
            continue
        mapping[uid] = value
    return Auth(mapping)
