# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Settings (JSON, 0600, atomic). Every default is editable in the Settings dialog or the file."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from task_resources import paths

SCHEMA = 2
OLD_MANAGED_DEFAULT = "/library/task-resources"   # 0.1.0/0.2.0 default, migrated (4E audit)


@dataclass
class Settings:
    # Folders scanned read-only. Nothing is ever created, chowned or written inside them.
    scan_dirs: list = field(default_factory=lambda: ["/library/zims/content", "/library/working/zims"])
    # Kiwix library files read for metadata (read-only).
    library_xml: list = field(default_factory=lambda: ["/library/zims/library.xml"])
    kiwix_desktop_dir: str = "~/.local/share/kiwix-desktop"
    # Managed storage, used ONLY for an explicit "copy into managed storage" (and 4E downloads).
    # 4E audit (Joshua): per-user storage only; /library is never written.
    managed_root: str = "~/.local/share/task-resources/downloads"
    # Folders T.A.S.K. never writes into (downloads/copies there are refused). Read-only scanning is unaffected.
    protected_roots: list = field(default_factory=lambda: ["/library"])
    # Reserved for later: additional user-approved storage locations (not used yet).
    extra_storage: list = field(default_factory=list)
    free_space_reserve_mb: int = 1024
    # Reader: "auto" (WebEngine if installed, else lightweight), "webengine" or "lightweight".
    viewer: str = "auto"
    open_archive_cache: int = 8          # open sources kept (memory bound)
    max_item_mb: int = 64                # largest single entry loaded into a viewer
    # Phase 4E: online catalog + downloads (nothing is contacted until the user asks).
    catalog_url: str = "https://opds.library.kiwix.org/catalog/v2"
    max_download_gb: int = 256           # per-file size limit
    schema: int = SCHEMA

    def expanded_kiwix_desktop(self) -> Path:
        return Path(os.path.expanduser(self.kiwix_desktop_dir))


def settings_path() -> Path:
    return paths.config_dir() / "settings.json"


def load(path: Path = None) -> Settings:
    path = path or settings_path()
    s = Settings()
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return s
    for k, v in data.items():
        if k == "schema":
            continue
        if hasattr(s, k) and type(v) is type(getattr(s, k)):
            setattr(s, k, v)
    if int(data.get("schema", 1)) < 2 and data.get("managed_root") == OLD_MANAGED_DEFAULT:
        s.managed_root = Settings.managed_root        # old default, never chosen by the user explicitly
    s.schema = SCHEMA
    return s


def save(s: Settings, path: Path = None) -> Path:
    path = path or settings_path()
    paths.private_dir(path.parent)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(asdict(s), f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path
