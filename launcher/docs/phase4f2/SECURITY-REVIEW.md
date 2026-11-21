# Phase 4F.2 security review (task-launcher 0.3.4)
* **Index access:** SQLite URI `mode=ro` and parameterised SQL only. The DB file is hash-verified unchanged (M17). SQLite may read the existing `-wal`/`-shm` sidecars; it never writes content. A newer schema is refused.
* **No new processes from the view itself.** Opening an item reuses the existing guarded paths:
  * `open_external` (localhost/absolute paths only, `xdg-open`, argv, no shell);
  * the Library tile route (`ProcessManager`, single instance);
  * the in-process Kiwix viewer.
  M16 confirms there are no subprocess calls on open/refresh.
* **No network.** Index reads are local (M09). Kiwix is still probed only by the existing background readiness worker (loopback).
* No root, no autostart, no services, no Core/auth change, no patient data and no logging of content (the log records only a failed view build).
* **Lock:** locking returns to Home under the overlay, so Medical content is never left visible (M19).
