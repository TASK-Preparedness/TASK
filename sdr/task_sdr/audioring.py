# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Thread-safe bounded audio FIFO between the DSP thread (producer) and the audio sink (consumer).

0.2.4. Pure Python/numpy (no Qt) so it is unit-testable. Nothing is ever discarded silently:
  * overrun  = the producer outran the sink; the OLDEST samples are dropped to keep latency bounded
               (counted in samples and events),
  * underrun = the sink asked for audio and the FIFO was empty/short; the sink gets silence padding
               (counted in samples and events) and the FIFO re-primes to the target latency before
               releasing audio again, so a starved stream recovers smoothly instead of stuttering.
Latency budget (explicit): target = prime level, max = hard cap. Defaults 150 ms / 500 ms at 48 kHz."""

import threading

import numpy as np

RATE = 48_000
TARGET_MS = 150
MAX_MS = 500


class AudioRing:
    def __init__(self, rate=RATE, target_ms=TARGET_MS, max_ms=MAX_MS):
        self.rate = int(rate)
        self.target = int(self.rate * target_ms / 1000)
        self.cap = int(self.rate * max_ms / 1000)
        if not 0 < self.target < self.cap:
            raise ValueError("need 0 < target < max latency")
        self._buf = np.zeros(self.cap, np.float32)
        self._r = 0              # read index
        self._n = 0              # samples stored
        self._lock = threading.Lock()
        self.primed = False
        self.generated = 0       # samples offered by the producer
        self.accepted = 0        # samples handed to the sink (real audio, not padding)
        self.overrun_samples = 0
        self.overrun_events = 0
        self.underrun_samples = 0
        self.underrun_events = 0
        self._in_underrun = False
        self.max_level = 0
        self.ever_primed = False  # silence before the first prime is start-up fill, not an underrun
        self.startup_samples = 0

    # ------------------------------------------------------------ producer
    def push(self, a):
        a = np.asarray(a, np.float32).ravel()
        with self._lock:
            self.generated += len(a)
            if len(a) >= self.cap:                       # pathological: keep only the newest cap samples
                drop = self._n + len(a) - self.cap
                self._r, self._n = 0, 0
                a = a[-self.cap:]
                self.overrun_samples += drop
                self.overrun_events += 1
            else:
                over = self._n + len(a) - self.cap
                if over > 0:                             # drop the OLDEST to bound latency
                    self._r = (self._r + over) % self.cap
                    self._n -= over
                    self.overrun_samples += over
                    self.overrun_events += 1
            w = (self._r + self._n) % self.cap
            k = min(len(a), self.cap - w)
            self._buf[w:w + k] = a[:k]
            self._buf[:len(a) - k] = a[k:]
            self._n += len(a)
            self.max_level = max(self.max_level, self._n)
            if not self.primed and self._n >= self.target:
                self.primed = self.ever_primed = True

    # ------------------------------------------------------------ consumer
    def pull(self, n, pad=True):
        """Up to n samples. pad=True (pull-mode sink): always returns exactly n samples, silence-padded and
        counted as underrun. pad=False (push mode): returns only real audio (possibly fewer than n)."""
        n = int(n)
        with self._lock:
            take = min(n, self._n) if self.primed else 0
            out = np.empty(take, np.float32)
            k = min(take, self.cap - self._r)
            out[:k] = self._buf[self._r:self._r + k]
            out[k:] = self._buf[:take - k]
            self._r = (self._r + take) % self.cap
            self._n -= take
            self.accepted += take
            short = n - take
            if short > 0 and pad and not self.ever_primed:
                self.startup_samples += short
            elif short > 0 and pad:
                if not self._in_underrun:
                    self.underrun_events += 1
                self._in_underrun = True
                self.underrun_samples += short
                if self._n == 0:
                    self.primed = False                  # re-prime to the target latency
            elif take:
                self._in_underrun = False
        if short > 0 and pad:
            out = np.concatenate((out, np.zeros(short, np.float32)))
        return out

    def note_push_starved(self, n):
        """Push mode: the sink had room for n samples and we had nothing (counted as an underrun)."""
        with self._lock:
            if n > 0 and self.ever_primed:
                if not self._in_underrun:
                    self.underrun_events += 1
                self._in_underrun = True
                self.underrun_samples += int(n)
                self.primed = self._n >= self.target

    def unread(self, a):
        """Push mode: return samples the sink did not accept to the FRONT of the FIFO (never lost)."""
        a = np.asarray(a, np.float32).ravel()
        if not len(a):
            return
        with self._lock:
            self.accepted -= len(a)
            room = self.cap - self._n
            if len(a) > room:                            # cannot happen in normal use; count, keep newest
                self.overrun_samples += len(a) - room
                self.overrun_events += 1
                a = a[len(a) - room:]
            self._r = (self._r - len(a)) % self.cap
            k = min(len(a), self.cap - self._r)
            self._buf[self._r:self._r + k] = a[:k]
            self._buf[:len(a) - k] = a[k:]
            self._n += len(a)

    def clear(self):
        with self._lock:
            self._r = self._n = 0
            self.primed = self.ever_primed = False
            self._in_underrun = False

    # ------------------------------------------------------------ compat + stats
    def level(self):
        with self._lock:
            return self._n

    def qsize(self):
        return self.level()

    def empty(self):
        return self.level() == 0

    def latency_ms(self):
        return 1000.0 * self.level() / self.rate

    def stats(self):
        with self._lock:
            return {"generated": self.generated, "accepted": self.accepted, "queued": self._n,
                    "queue_ms": round(1000.0 * self._n / self.rate, 1), "max_queue_ms":
                    round(1000.0 * self.max_level / self.rate, 1), "target_ms": round(1000.0 * self.target /
                    self.rate, 1), "cap_ms": round(1000.0 * self.cap / self.rate, 1),
                    "overrun_samples": self.overrun_samples, "overrun_events": self.overrun_events,
                    "underrun_samples": self.underrun_samples, "underrun_events": self.underrun_events,
                    "startup_fill_samples": self.startup_samples}
