# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Background map downloader: rate-limited, bounded-concurrency, resumable.

* One ``DownloadEngine`` per running job: a producer thread walks the job's tiles from the saved
  cursor (skipping tiles already in the map file) and ``source.max_concurrency`` worker threads
  fetch them. All workers share one ``RateLimiter`` (``source.rate_limit`` requests/s).
* HTTP 429/503 put **every** worker on hold for ``Retry-After`` (seconds or HTTP-date, capped).
  5xx/408 are retried with bounded exponential backoff and jitter; 404/204 mean "not available
  from this source" and are recorded as failed without retries; 401/403 repeated → job paused.
* Connection-level errors (no HTTP response) for ``net_fail_threshold`` consecutive requests →
  state *waiting-network*; workers retry with backoff and the job resumes by itself once a
  request succeeds.
* Downloaded bytes are validated, then queued to the single ``TileWriter`` of the source's
  MBTiles file; a tile only counts as done after its transaction committed.
* Disk full (SQLITE_FULL) or free space below the reserve → state *paused-disk* with a clear
  message; nothing is corrupted and the job resumes from its cursor.
"""

import collections
import random
import shutil
import threading
import time
import queue
from pathlib import Path

from task_maps import USER_AGENT, mbtiles, net
from task_maps.jobs import ACTIVE, DuplicateJob, JobStore  # noqa: F401 (re-export)
from task_maps.mbtiles import MBTilesError, validate_tile
from task_maps.sources import download_permission
from task_maps.tilemath import BBox, count_tiles, iter_tiles

DEFAULT_RESERVE = 200 * 1024 * 1024
SQLITE_OVERHEAD = 1.15


class RateLimiter:
    """Global spacing of request starts: at most ``rate`` per second across all threads."""

    def __init__(self, rate: float, clock=time.monotonic):
        self.interval = 1.0 / rate
        self.clock = clock
        self._next = 0.0
        self._lock = threading.Lock()

    def reserve(self) -> float:
        with self._lock:
            now = self.clock()
            t = max(now, self._next)
            self._next = t + self.interval
            return t - now


def estimate(bbox: BBox, minz: int, maxz: int, avg_tile_bytes: float, free_bytes: int, reserve=DEFAULT_RESERVE):
    """Tile count, estimated bytes and whether it fits. Returns a dict."""
    n = count_tiles(bbox, minz, maxz)
    est = int(n * avg_tile_bytes)
    need = int(est * SQLITE_OVERHEAD)
    return {"tiles": n, "bytes": est, "required": need, "free": free_bytes,
            "fits": need + reserve <= free_bytes, "reserve": reserve}


def human_bytes(n) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def human_eta(seconds) -> str:
    if seconds is None:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min {seconds % 60:02d} s"
    return f"{seconds // 3600} h {seconds % 3600 // 60:02d} min"


class DownloadEngine:
    def __init__(self, store: JobStore, job_id: int, source, writer, map_path, fetch=net.fetch, api_key="",
                 ua=USER_AGENT, free_space=None, reserve_bytes=DEFAULT_RESERVE, on_progress=None, on_state=None,
                 max_attempts=5, backoff_base=1.0, backoff_cap=60.0, net_fail_threshold=3, net_backoff_cap=60.0,
                 forbidden_threshold=5, clock=time.monotonic, rng=random.random, checkpoint_s=1.0,
                 capacity_every=100):
        self.store, self.job_id, self.source, self.writer = store, job_id, source, writer
        self.map_path = Path(map_path)
        self.fetch, self.api_key, self.ua = fetch, api_key, ua
        self.free_space = free_space or (lambda: shutil.disk_usage(self.map_path.parent).free)
        self.reserve = reserve_bytes
        self.on_progress, self.on_state = on_progress, on_state
        self.max_attempts, self.backoff_base, self.backoff_cap = max_attempts, backoff_base, backoff_cap
        self.net_fail_threshold, self.net_backoff_cap = net_fail_threshold, net_backoff_cap
        self.forbidden_threshold = forbidden_threshold
        self.clock, self.rng = clock, rng
        self.checkpoint_s, self.capacity_every = checkpoint_s, capacity_every
        self.limiter = RateLimiter(source.rate_limit, clock)
        self.concurrency = max(1, min(source.max_concurrency, 4))
        job = store.get(job_id)
        self.job = job
        self.cursor = job.cursor
        self.downloaded, self.skipped, self.failed, self.bytes = job.downloaded, job.skipped, job.failed, job.bytes
        self.state = "queued"
        self.message = ""
        self._lock = threading.RLock()
        self._done_above = set()
        self._produced_until = self.cursor
        self._run = threading.Event()
        self._run.set()
        self._stop = threading.Event()
        self._hold_until = 0.0
        self._net_failures = 0
        self._net_backoff = 2.0
        self._forbidden = 0
        self._q = queue.Queue(maxsize=self.concurrency * 4)
        self._retry = queue.Queue()           # tiles whose write failed (disk full): fetched again
        self._threads = []
        self._rate_window = collections.deque()
        self._last_cp = 0.0
        self._format_set = False
        self.finished = threading.Event()
        self.max_inflight_seen = 0
        self._inflight = 0

    # ---------------------------------------------------------------- control
    def start(self):
        ok, why = download_permission(self.source, self.api_key)
        if not ok:
            self._set_state("paused", f"download refused: {why}")
            self.finished.set()
            return False
        self._set_state("running", "")
        prod = threading.Thread(target=self._producer, name=f"dl-producer-{self.job_id}", daemon=True)
        self._threads = [prod] + [threading.Thread(target=self._worker, name=f"dl-worker-{self.job_id}-{i}", daemon=True)
                                  for i in range(self.concurrency)]
        for t in self._threads:
            t.start()
        return True

    def pause(self, state="paused", message="paused by the user"):
        self._run.clear()
        self._set_state(state, message)
        self._checkpoint(force=True)

    def resume(self):
        if self._stop.is_set():
            return
        if self.writer.full:
            self.writer.reset_full()
        self._run.set()
        self._set_state("running", "")

    def cancel(self):
        self._stop.set()
        self._run.set()
        self._set_state("cancelled", "cancelled by the user")

    def shutdown(self, timeout=5.0):
        """Stop threads without changing the saved state (program exit); the job resumes later."""
        state = self.state
        self._stop.set()
        self._run.set()
        for t in self._threads:
            t.join(timeout)
        self._checkpoint(force=True)
        if state == "running":
            self.store.set_state(self.job_id, "interrupted", "the program was closed during this download")

    def wait(self, timeout=None) -> bool:
        return self.finished.wait(timeout)

    # ---------------------------------------------------------------- state
    def _set_state(self, state, message):
        with self._lock:
            self.state, self.message = state, message
        self.store.set_state(self.job_id, state, message)
        if self.on_state:
            self.on_state(self.job_id, state, message)
        self._emit()

    def snapshot(self) -> dict:
        with self._lock:
            now = self.clock()
            while self._rate_window and now - self._rate_window[0] > 20.0:
                self._rate_window.popleft()
            span = (now - self._rate_window[0]) if len(self._rate_window) > 1 else 0.0
            rate = (len(self._rate_window) - 1) / span if span > 0.5 else 0.0
            finished = self.cursor + len(self._done_above)
            remaining = max(0, self.job.total - finished)
            return {"job_id": self.job_id, "state": self.state, "message": self.message, "total": self.job.total,
                    "finished": finished, "downloaded": self.downloaded, "skipped": self.skipped,
                    "failed": self.failed, "bytes": self.bytes, "rate": rate,
                    "eta": (remaining / rate) if rate > 0 else None}

    def _emit(self):
        if self.on_progress:
            self.on_progress(self.snapshot())

    def _checkpoint(self, force=False):
        now = self.clock()
        if not force and now - self._last_cp < self.checkpoint_s:
            return
        self._last_cp = now
        with self._lock:
            args = (self.cursor, self.downloaded, self.skipped, self.failed, self.bytes)
        self.store.checkpoint(self.job_id, *args)
        self._emit()

    def _complete(self, idx):
        with self._lock:
            self._inflight = max(0, self._inflight - 1)
            if idx == self.cursor:
                self.cursor += 1
                while self.cursor in self._done_above:
                    self._done_above.discard(self.cursor)
                    self.cursor += 1
            elif idx > self.cursor:
                self._done_above.add(idx)
        self._checkpoint()

    # ---------------------------------------------------------------- producer
    def _wait_runnable(self) -> bool:
        while not self._stop.is_set():
            if not self._run.is_set():
                self._run.wait(0.2)
                continue
            hold = self._hold_until - self.clock()
            if hold > 0:
                self._stop.wait(min(hold, 0.5))
                continue
            return True
        return False

    def _producer(self):
        reader = None
        try:
            reader = mbtiles.Reader(self.map_path)
            n = 0
            for idx, z, x, y in iter_tiles(self.job.bbox, self.job.minz, self.job.maxz, start=self.cursor):
                if not self._wait_runnable():
                    return
                n += 1
                if n % self.capacity_every == 0:
                    try:
                        free = self.free_space()
                    except OSError:
                        free = None
                    if free is not None and free < self.reserve:
                        self.pause("paused-disk", f"storage low: {human_bytes(free)} free (reserve "
                                   f"{human_bytes(self.reserve)}); free space and resume")
                        if not self._wait_runnable():
                            return
                try:
                    present = reader.has(z, x, y)
                except Exception:   # noqa: BLE001 - treat a read problem as "not present"
                    present = False
                if present:
                    with self._lock:
                        self.skipped += 1
                        self._inflight += 1
                    self._complete(idx)
                    continue
                with self._lock:
                    self._inflight += 1
                    self.max_inflight_seen = max(self.max_inflight_seen, self._inflight)
                while not self._stop.is_set():
                    try:
                        self._q.put((idx, z, x, y), timeout=0.2)
                        break
                    except queue.Full:
                        continue
            # every tile is queued: wait until all are committed or recorded as failed
            while not self._stop.is_set():
                with self._lock:
                    pending = self._inflight
                if pending == 0 and self._retry.empty():
                    break
                self._stop.wait(0.05)
            for _ in range(self.concurrency):
                while not self._stop.is_set():
                    try:
                        self._q.put(None, timeout=0.2)
                        break
                    except queue.Full:
                        continue
            for t in self._threads[1:]:
                while t.is_alive() and not self._stop.is_set():
                    t.join(0.2)
            if self._stop.is_set():
                return
            self._checkpoint(force=True)
            if self.state == "running" and self.cursor >= self.job.total:
                self._set_state("completed-with-errors" if self.failed else "completed",
                                f"{self.failed} tile(s) failed" if self.failed else "")
        except Exception as exc:   # noqa: BLE001 - report instead of dying silently
            self.pause("paused", f"internal error: {exc}")
        finally:
            if reader:
                reader.close()
            if self._stop.is_set():
                self._checkpoint(force=True)
            self.finished.set()

    # ---------------------------------------------------------------- workers
    def _backoff(self, attempt) -> float:
        base = min(self.backoff_cap, self.backoff_base * (2 ** max(0, attempt - 1)))
        return base * (0.5 + self.rng() * 0.5)

    def _fail(self, idx, z, x, y, attempts, error):
        self.store.record_failed(self.job_id, z, x, y, attempts, self.source.redact(error, self.api_key))
        with self._lock:
            self.failed += 1
        self._complete(idx)

    def _hold(self, seconds):
        with self._lock:
            self._hold_until = max(self._hold_until, self.clock() + seconds)

    def _network_error(self, exc):
        with self._lock:
            self._net_failures += 1
            n = self._net_failures
            wait = self._net_backoff
            if n >= self.net_fail_threshold:
                self._net_backoff = min(self.net_backoff_cap, self._net_backoff * 2)
        if n >= self.net_fail_threshold:
            if self.state == "running":
                self._set_state("waiting-network", f"network unreachable ({self.source.redact(str(exc), self.api_key)}); "
                                "retrying automatically")
            self._hold(wait * (0.75 + self.rng() * 0.5))
        else:
            self._hold(min(2.0, wait))

    def _network_ok(self):
        with self._lock:
            self._net_failures = 0
            self._net_backoff = 2.0
        if self.state == "waiting-network":
            self._set_state("running", "network is back")

    def _committed(self, idx, z, x, y, nbytes, fmt, ok, err):
        if ok:
            with self._lock:
                if err != "duplicate":
                    self.downloaded += 1
                    self.bytes += nbytes
                    self._rate_window.append(self.clock())
                else:
                    self.skipped += 1
            self.store.clear_failed(self.job_id, z, x, y)
            self._complete(idx)
        elif "disk full" in err:
            self._retry.put((idx, z, x, y))      # still in flight; fetched again after resume
            if self.state != "paused-disk":
                self.pause("paused-disk", "disk full — the map file was not changed; free space and resume")
        else:
            self._fail(idx, z, x, y, 1, err)

    def _worker(self):
        while not self._stop.is_set():
            try:
                item = self._retry.get_nowait()
            except queue.Empty:
                try:
                    item = self._q.get(timeout=0.2)
                except queue.Empty:
                    continue
            if item is None:
                return
            self._fetch_tile(*item)

    def _fetch_tile(self, idx, z, x, y):
        attempts = holds = corrupt = 0
        while True:
            if not self._wait_runnable():
                return
            wait = self.limiter.reserve()
            if wait > 0 and self._stop.wait(wait):
                return
            if not self._wait_runnable():
                return
            url = self.source.tile_url(z, x, y, self.api_key)
            try:
                resp = self.fetch(url, self.ua)
            except net.NetworkError as exc:
                self._network_error(exc)
                continue
            self._network_ok()
            st = resp.status
            if st == 200:
                try:
                    fmt = validate_tile(resp.body)
                except MBTilesError as exc:
                    corrupt += 1
                    if corrupt >= 2:
                        self._fail(idx, z, x, y, attempts + corrupt, f"corrupt tile rejected: {exc}")
                        return
                    continue
                self._forbidden = 0
                if not self._format_set:
                    self._format_set = True
                    self.writer.set_metadata({"format": fmt})
                body = resp.body
                self.writer.put(mbtiles.Write(z, x, y, body, on_done=lambda ok, err, n=len(body), f=fmt:
                                              self._committed(idx, z, x, y, n, f, ok, err)))
                return
            if st in (204, 404):
                self._fail(idx, z, x, y, attempts + 1, f"not available from this source (HTTP {st})")
                return
            if st in (429, 503):
                holds += 1
                delay = net.retry_after(resp.headers, default=self._backoff(holds))
                self._hold(delay)
                if holds > 20:
                    self._fail(idx, z, x, y, attempts + holds, f"server kept answering HTTP {st}")
                    return
                continue
            if st in (401, 403):
                self._forbidden += 1
                self._fail(idx, z, x, y, attempts + 1, f"access refused (HTTP {st})")
                if self._forbidden >= self.forbidden_threshold and self.state == "running":
                    self.pause("paused", f"the server refuses access (HTTP {st}); check the source's API key/terms")
                return
            attempts += 1
            if attempts >= self.max_attempts:
                self._fail(idx, z, x, y, attempts, f"HTTP {st} after {attempts} attempts")
                return
            if self._stop.wait(self._backoff(attempts)):
                return


class JobManager:
    """Owns the job store, one TileWriter per map file and at most one running engine.

    Callbacks (called from background threads; the Qt layer marshals them):
    ``on_progress(snapshot)``, ``on_state(job_id, state, message)``, ``on_tiles(map_path, [(z,x,y)])``,
    ``on_disk_full(message)``.
    """

    def __init__(self, data_dir, catalog, keys=None, ua=USER_AGENT, fetch=net.fetch, reserve_bytes=DEFAULT_RESERVE,
                 engine_kwargs=None, free_space=None):
        self.data_dir = Path(data_dir)
        self.maps_dir = self.data_dir / "maps"
        self.maps_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.store = JobStore(self.data_dir / "jobs.sqlite")
        self.catalog = catalog
        self.keys = keys or {}
        self.ua, self.fetch, self.reserve = ua, fetch, reserve_bytes
        self.engine_kwargs = engine_kwargs or {}
        self.free_space = free_space or (lambda: shutil.disk_usage(self.maps_dir).free)
        self.writers = {}
        self.engine = None
        self.on_progress = self.on_state = self.on_tiles = self.on_disk_full = None
        self._lock = threading.RLock()

    def map_path(self, source_id) -> Path:
        return self.maps_dir / f"{source_id}.mbtiles"

    def writer_for(self, source):
        path = self.map_path(source.id)
        with self._lock:
            w = self.writers.get(str(path))
            if w is None or not w.is_alive():
                if not path.exists():
                    mbtiles.create(path, {"name": source.name, "type": "baselayer", "version": "1.0",
                                          "description": f"Downloaded by task-maps from {source.name}",
                                          "attribution": source.attribution, "task_maps_source": source.id,
                                          "format": source.format if source.format != "auto" else "png"})
                w = mbtiles.TileWriter(path, on_commit=lambda tiles, p=str(path): self._tiles(p, tiles),
                                       on_disk_full=self._disk_full)
                w.start()
                self.writers[str(path)] = w
            return w

    def _tiles(self, path, tiles):
        if self.on_tiles:
            self.on_tiles(path, tiles)

    def _disk_full(self, msg):
        if self.on_disk_full:
            self.on_disk_full(msg)

    def estimate(self, source, bbox, minz, maxz):
        avg = source.avg_tile_bytes
        p = self.map_path(source.id)
        if p.exists():
            try:
                r = mbtiles.Reader(p)
                n, a = r.stats()
                r.close()
                if n >= 50 and a > 0:
                    avg = a
            except Exception:   # noqa: BLE001
                pass
        try:
            free = self.free_space()
        except OSError:
            free = 0
        return estimate(bbox, minz, maxz, avg, free, self.reserve)

    def create_job(self, source_id, name, bbox: BBox, minz, maxz):
        src = self.catalog.sources.get(source_id)
        if src is None:
            raise ValueError(f"unknown source {source_id!r}")
        ok, why = download_permission(src, self.keys.get(src.id, ""))
        if not ok:
            raise PermissionError(why)
        if not (src.min_zoom <= minz <= maxz <= src.max_zoom):
            raise ValueError(f"zoom range must be within {src.min_zoom}–{src.max_zoom} for this source")
        est = self.estimate(src, bbox, minz, maxz)
        if est["tiles"] == 0:
            raise ValueError("the area contains no tiles")
        if est["tiles"] > src.max_tiles_per_job:
            raise ValueError(f"{est['tiles']:,} tiles exceeds this source's limit of {src.max_tiles_per_job:,} per "
                             "download; choose a smaller area or fewer zoom levels")
        if not est["fits"]:
            raise OSError(f"not enough free space: about {human_bytes(est['required'])} needed plus "
                          f"{human_bytes(self.reserve)} reserve, {human_bytes(est['free'])} free")
        w = self.writer_for(src)
        job = self.store.create(src.id, name, bbox, minz, maxz, est["tiles"], self.map_path(src.id))
        self._update_bounds(w, src)
        return job

    def _update_bounds(self, writer, src):
        jobs = [j for j in self.store.list() if j.source_id == src.id and j.state != "cancelled"]
        if not jobs:
            return
        if any(j.bbox.crosses_antimeridian for j in jobs):
            w, e = -180.0, 180.0
        else:
            w, e = min(j.bbox.west for j in jobs), max(j.bbox.east for j in jobs)
        s, n = min(j.bbox.south for j in jobs), max(j.bbox.north for j in jobs)
        writer.set_metadata({"bounds": f"{w:.6f},{s:.6f},{e:.6f},{n:.6f}",
                             "center": f"{(w + e) / 2:.6f},{(s + n) / 2:.6f},{min(j.minz for j in jobs)}",
                             "minzoom": min(j.minz for j in jobs), "maxzoom": max(j.maxz for j in jobs)})

    def start(self, job_id):
        with self._lock:
            if self.engine and not self.engine.finished.is_set():
                if self.engine.job_id == job_id:
                    self.engine.resume()
                    return self.engine
                raise RuntimeError("another download is running; pause or cancel it first")
            job = self.store.get(job_id)
            src = self.catalog.sources.get(job.source_id)
            if src is None:
                self.store.set_state(job_id, "paused", f"source {job.source_id!r} is no longer defined")
                return None
            w = self.writer_for(src)
            kw = dict(self.engine_kwargs)
            kw.setdefault("free_space", self.free_space)
            self.engine = DownloadEngine(self.store, job_id, src, w, self.map_path(src.id), fetch=self.fetch,
                                         api_key=self.keys.get(src.id, ""), ua=self.ua, reserve_bytes=self.reserve,
                                         on_progress=self._progress, on_state=self._state, **kw)
            self.engine.start()
            return self.engine

    def _progress(self, snap):
        if self.on_progress:
            self.on_progress(snap)

    def _state(self, job_id, state, message):
        if self.on_state:
            self.on_state(job_id, state, message)

    def pause(self):
        if self.engine and not self.engine.finished.is_set():
            self.engine.pause()

    def resume(self, job_id=None):
        if self.engine and not self.engine.finished.is_set() and (job_id is None or job_id == self.engine.job_id):
            self.engine.resume()
            return self.engine
        if job_id is not None:
            return self.start(job_id)
        return None

    def cancel(self, job_id=None):
        if self.engine and not self.engine.finished.is_set() and (job_id is None or job_id == self.engine.job_id):
            self.engine.cancel()
            self.engine.wait(5)
        elif job_id is not None:
            self.store.set_state(job_id, "cancelled", "cancelled by the user")

    def retry_failed(self, job_id):
        job = self.store.get(job_id)
        if job is None or (self.engine and not self.engine.finished.is_set()):
            return None
        with self.store._lock, self.store.con:
            self.store.con.execute("DELETE FROM failed_tiles WHERE job_id=?", (job_id,))
            self.store.con.execute("UPDATE jobs SET cursor=0, skipped=0, failed=0, state='queued', message='' "
                                   "WHERE id=?", (job_id,))
        return self.start(job_id)

    def active_job_ids(self):
        return [j.id for j in self.store.list() if j.active]

    def failed_tiles_for(self, map_path):
        out = set()
        for j in self.store.list():
            if j.map_path == str(map_path):
                out.update((z, x, y) for z, x, y, _, _ in self.store.failed_tiles(job_id=j.id))
        return out

    def running_job(self):
        if self.engine and not self.engine.finished.is_set():
            return self.store.get(self.engine.job_id)
        return None

    def shutdown(self):
        if self.engine and not self.engine.finished.is_set():
            self.engine.shutdown()
        for w in list(self.writers.values()):
            w.stop()
        self.store.close()
