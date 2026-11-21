# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Tab A "Import from Pi": register files in place (default) or copy into managed storage."""

import os
from dataclasses import dataclass

from task_resources import discovery, managed


@dataclass
class ImportResult:
    path: str
    rid: int = None
    status: str = ""         # registered | copied | duplicate | error
    message: str = ""


def import_paths(library, paths, categories=(), overrides=None, managed_copy=False, allow_duplicate=False,
                 job=None):
    idx, out = library.index, []
    files = []
    for p in paths:
        if os.path.isdir(p):   # a folder: its supported files (unsupported ones are skipped, not errors)
            files += [str(f) for f in discovery.walk(p)
                      if f.suffix.lower() in discovery.SCAN_EXT or f.suffix.lower() == ".zimaa"]
        else:
            files.append(str(p))
    for i, f in enumerate(files):
        if job:
            job.progress(done=i, total=len(files), message=f)
        target, note = f, ""
        rep = discovery.Report()
        if managed_copy:
            try:
                dest, note = managed.copy_in(f, library.settings, categories[0] if categories else "", job)
                target = str(dest)
            except (OSError, managed.ManagedError) as exc:
                out.append(ImportResult(f, status="error", message=str(exc)))
                continue
        rid = discovery.register(idx, target, "managed" if managed_copy else "import", rep,
                                 allow_duplicate=allow_duplicate or managed_copy, keep_duplicate=False,
                                 managed=managed_copy)
        if rid is None:
            reason = rep.errors[-1][1] if rep.errors else "not registered"
            out.append(ImportResult(f, status="duplicate" if reason.startswith("duplicate") else "error",
                                    message=reason))
            continue
        for c in categories:
            idx.add_to_category(rid, c)
        for k, v in (overrides or {}).items():
            if v:
                idx.set_override(rid, k, v)
        out.append(ImportResult(f, rid, "copied" if managed_copy else "registered",
                                note or ("copied to " + target if managed_copy else "registered in place")))
    return out
