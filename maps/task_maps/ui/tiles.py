# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Asynchronous tile loading and the bounded in-memory cache.

Worker threads (``threading``) own their own read-only SQLite connections and decode tiles to
``QImage`` (QImage, unlike QPixmap, is safe to create off the GUI thread). Results reach the GUI
thread through a queued Qt signal. Requests are de-duplicated, served newest-first (LIFO) and
dropped when they belong to an outdated view generation.
"""

import collections
import queue
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from task_maps import mbtiles

ABSENT = object()       # tile known not to exist in the file


class LRU:
    def __init__(self, maxsize):
        self.maxsize = max(1, maxsize)
        self.d = collections.OrderedDict()

    def get(self, k, default=None):
        v = self.d.get(k, default)
        if k in self.d:
            self.d.move_to_end(k)
        return v

    def put(self, k, v):
        self.d[k] = v
        self.d.move_to_end(k)
        while len(self.d) > self.maxsize:
            self.d.popitem(last=False)

    def pop(self, k):
        return self.d.pop(k, None)

    def __contains__(self, k):
        return k in self.d

    def __len__(self):
        return len(self.d)

    def clear(self):
        self.d.clear()


class TileCache:
    """Decoded images (bounded by count) + a larger bounded set of known-absent tiles."""

    def __init__(self, max_images=512, max_absent=50_000):
        self.images = LRU(max_images)
        self.absent = LRU(max_absent)

    def lookup(self, key):
        img = self.images.get(key)
        if img is not None:
            return img
        if key in self.absent:
            self.absent.get(key)
            return ABSENT
        return None

    def store(self, key, img):
        if img is None:
            self.absent.put(key, True)
            self.images.pop(key)
        else:
            self.images.put(key, img)
            self.absent.pop(key)

    def invalidate(self, key):
        self.images.pop(key)
        self.absent.pop(key)

    def clear(self):
        self.images.clear()
        self.absent.clear()


class TileLoader(QObject):
    """``request(path, z, x, y)``; emits ``loaded(path, z, x, y, image_or_None, error)``."""

    loaded = Signal(str, int, int, int, object, str)

    def __init__(self, threads=2, parent=None):
        super().__init__(parent)
        self._q = collections.deque()
        self._cv = threading.Condition()
        self._pending = set()
        self._stop = False
        self.generation = 0
        self.decoded = 0
        self.providers = {}                 # "online:<source>" -> online.OnlineSource
        self._threads = [threading.Thread(target=self._run, name=f"tile-loader-{i}", daemon=True) for i in range(threads)]
        for t in self._threads:
            t.start()

    def request(self, path, z, x, y, front=True):
        key = (path, z, x, y)
        with self._cv:
            if key in self._pending:
                return
            self._pending.add(key)
            item = (self.generation, key)
            if front:
                self._q.append(item)
            else:
                self._q.appendleft(item)
            if len(self._q) > 4000:                 # drop the oldest requests
                g, old = self._q.popleft()
                self._pending.discard(old)
            self._cv.notify()

    def new_generation(self, keep=8):
        """Called when the view jumps far: forget queued requests except the newest ``keep``."""
        with self._cv:
            self.generation += 1
            while len(self._q) > keep:
                g, old = self._q.popleft()
                self._pending.discard(old)

    def add_provider(self, provider):
        self.providers[provider.path] = provider
        provider.on_tile = lambda z, x, y, data, err, p=provider.path: self._net_tile(p, z, x, y, data, err)

    def set_wanted(self, path, keys):
        prov = self.providers.get(path)
        if prov is not None:
            prov.set_wanted(keys)

    @staticmethod
    def _decode(data):
        q = QImage()
        if q.loadFromData(data) and not q.isNull():
            return q.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied), ""
        return None, "corrupt"

    def _net_tile(self, path, z, x, y, data, err):
        img = None
        if data is not None:
            img, derr = self._decode(data)
            err = err or derr
        self.loaded.emit(path, z, x, y, img, err or "")

    def pending(self):
        with self._cv:
            return len(self._pending)

    def stop(self):
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        for t in self._threads:
            t.join(2)

    def _run(self):
        readers = {}
        try:
            while True:
                with self._cv:
                    while not self._q and not self._stop:
                        self._cv.wait()
                    if self._stop:
                        return
                    gen, key = self._q.pop()
                path, z, x, y = key
                img, err = None, ""
                prov = self.providers.get(path)
                if prov is not None:
                    try:
                        data, _origin = prov.local(z, x, y)
                    except Exception as exc:   # noqa: BLE001
                        data, err = None, str(exc)[:200]
                    with self._cv:
                        self._pending.discard(key)
                    if data is not None:
                        img, err = self._decode(data)
                        self.decoded += 1
                        self.loaded.emit(path, z, x, y, img, err)
                    elif not prov.request(z, x, y):
                        self.loaded.emit(path, z, x, y, None, "offline" if not prov.online else "missing")
                    continue
                try:
                    r = readers.get(path)
                    if r is None:
                        r = readers[path] = mbtiles.Reader(path)
                    data = r.get(z, x, y)
                    if data is not None:
                        q = QImage()
                        if q.loadFromData(data) and not q.isNull():
                            img = q.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                        else:
                            err = "corrupt"
                except Exception as exc:   # noqa: BLE001 - reported to the view
                    err = str(exc)[:200]
                    readers.pop(path, None)
                with self._cv:
                    self._pending.discard(key)
                self.decoded += 1
                self.loaded.emit(path, z, x, y, img, err)
        finally:
            for r in readers.values():
                r.close()
