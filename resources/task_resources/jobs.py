# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Small in-process background job runner (threads) with cooperative cancellation and progress.

4D uses it for scans, imports/managed copies and verification. The 4E download engine (resume,
atomic finalize, SSRF-safe redirects) is specified in docs/PHASE4E-SPEC.md and will build on this."""

import threading
import time
from dataclasses import dataclass, field

QUEUED, RUNNING, DONE, FAILED, CANCELLED = "queued", "running", "done", "failed", "cancelled"


class Cancelled(Exception):
    pass


@dataclass
class Job:
    name: str
    fn: object
    state: str = QUEUED
    done: int = 0
    total: int = 0
    message: str = ""
    result: object = None
    error: str = ""
    started: float = 0.0
    finished: float = 0.0
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    _thread: threading.Thread = field(default=None, repr=False)

    def cancel(self):
        self._cancel.set()

    @property
    def cancelled(self):
        return self._cancel.is_set()

    def check(self):
        if self._cancel.is_set():
            raise Cancelled()

    def progress(self, done=None, total=None, message=None):
        if done is not None:
            self.done = done
        if total is not None:
            self.total = total
        if message is not None:
            self.message = message
        self.check()

    def wait(self, timeout=None):
        if self._thread:
            self._thread.join(timeout)
        return self.state in (DONE, FAILED, CANCELLED)

    @property
    def active(self):
        return self.state in (QUEUED, RUNNING)


class JobRunner:
    def __init__(self):
        self.jobs = []
        self._lock = threading.Lock()

    def start(self, name, fn):
        """fn(job) runs in a daemon thread; it calls job.progress()/job.check() to honour cancel."""
        job = Job(name, fn)

        def run():
            job.state, job.started = RUNNING, time.time()
            try:
                job.result = fn(job)
                job.state = CANCELLED if job.cancelled else DONE
            except Cancelled:
                job.state = CANCELLED
            except Exception as exc:  # noqa: BLE001 - reported in the UI
                job.state, job.error = FAILED, f"{type(exc).__name__}: {exc}"
            job.finished = time.time()

        job._thread = threading.Thread(target=run, name=f"job-{name}", daemon=True)
        with self._lock:
            self.jobs.append(job)
        job._thread.start()
        return job

    def active(self):
        return [j for j in self.jobs if j.active]

    def cancel_all(self, timeout=5.0):
        for j in self.active():
            j.cancel()
        for j in list(self.jobs):
            j.wait(timeout)
