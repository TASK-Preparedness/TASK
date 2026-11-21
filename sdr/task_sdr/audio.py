# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Audio output through QtMultimedia QAudioSink, 48 kHz mono float32 (0.2.4: PULL mode by default).
The DSP thread pushes into a bounded AudioRing (task_sdr.audioring); Qt pulls from it on its own schedule, so audio
no longer depends on the GUI repaint timer and no sample is silently discarded. TASK_SDR_AUDIO_MODE=push selects a
push fallback that honours bytesFree() and partial writes.
The Direwolf sound card (its ADEVICE) is excluded from the output list so SDR audio can never reach a
transmitter's audio input."""

import os
import re
from pathlib import Path

import numpy as np

DIREWOLF_CONF = (Path.home() / "direwolf.conf", Path("/etc/direwolf.conf"))


def direwolf_cards(confs=DIREWOLF_CONF):
    """Card names/ids referenced by ADEVICE lines (read-only)."""
    out = set()
    for p in confs:
        try:
            text = Path(p).read_text(errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if line.upper().startswith("ADEVICE"):
                for tok in line.split()[1:]:
                    m = re.search(r"CARD=([A-Za-z0-9_]+)", tok) or re.search(r"hw:([A-Za-z0-9_]+)", tok)
                    if m:
                        out.add(m.group(1).lower())
    return out


def allowed_devices(devices, excluded_cards):
    """devices: [(id, description)] -> those not matching a Direwolf card."""
    res = []
    for dev_id, desc in devices:
        hay = f"{dev_id} {desc}".lower()
        if any(c in hay for c in excluded_cards):
            continue
        res.append((dev_id, desc))
    return res



MODES = ("pull", "push")
SINK_BUFFER_MS = 100          # Qt/PipeWire-side buffer (part of the explicit latency budget)
RESTART_S = 1.0


def _open_device(device_id, excluded):
    from PySide6.QtMultimedia import QMediaDevices
    devs = [d for d in QMediaDevices.audioOutputs()
            if allowed_devices([(bytes(d.id()).decode(errors="replace"), d.description())], excluded)]
    dev = next((d for d in devs if bytes(d.id()).decode(errors="replace") == device_id), None) or \
        (devs[0] if devs else None)
    if dev is None:
        raise OSError("no permitted audio output (the Direwolf card is excluded)")
    return dev


def make_pull_source(ring):
    """QIODevice that Qt reads (pull mode). readData always returns the requested amount: real audio from the ring,
    padded with counted silence on underrun, so the sink never drops into IdleState and stutters."""
    from PySide6.QtCore import QIODevice

    class RingSource(QIODevice):
        def __init__(self):
            super().__init__()
            self.ring = ring
            self.reads = 0

        def isSequential(self):
            return True

        def bytesAvailable(self):
            return max(4096, self.ring.level() * 4) + super().bytesAvailable()

        def readData(self, maxlen):
            n = int(maxlen) // 4
            self.reads += 1
            if n <= 0:
                return b""
            return self.ring.pull(n, pad=True).tobytes()

        def writeData(self, data):
            return -1

    src = RingSource()
    src.open(QIODevice.ReadOnly)
    return src


class QtAudioOut:
    """Owns the QAudioSink. Create and use it in the GUI thread only. engine pushes into self.ring (thread-safe)."""

    def __init__(self, device_id="", rate=48_000, ring=None, mode=None, log=None):
        from PySide6.QtCore import QTimer
        from PySide6.QtMultimedia import QAudioFormat
        from task_sdr.audioring import AudioRing
        self.rate, self.device_id = int(rate), device_id
        self.ring = ring or AudioRing(self.rate)
        self.mode = (mode or os.environ.get("TASK_SDR_AUDIO_MODE") or "pull").lower()
        if self.mode not in MODES:
            self.mode = "pull"
        self.log = log or (lambda msg: None)
        self.fmt = QAudioFormat()
        self.fmt.setSampleRate(self.rate)
        self.fmt.setChannelCount(1)
        self.fmt.setSampleFormat(QAudioFormat.Float)
        self.excluded = direwolf_cards()
        self.sink = self.io = self.src = None
        self.errors = 0
        self.restarts = 0
        self.idle_events = 0
        self.partial_writes = 0
        self.bytes_written = 0
        self.last_error = None
        self.closed = False
        self._open()                                    # raises OSError when there is no permitted output
        self.pump = QTimer()
        self.pump.setInterval(10)
        self.pump.timeout.connect(self._pump)
        if self.mode == "push":
            self.pump.start()
        try:
            from PySide6.QtMultimedia import QMediaDevices
            self._md = QMediaDevices()
            self._md.audioOutputsChanged.connect(self._outputs_changed)
        except Exception:  # noqa: BLE001 — device-change notification is optional
            self._md = None

    def _open(self):
        from PySide6.QtMultimedia import QAudioSink
        dev = _open_device(self.device_id, self.excluded)
        self.dev_desc = dev.description()
        self.sink = QAudioSink(dev, self.fmt)
        self.sink.setBufferSize(int(self.rate * 4 * SINK_BUFFER_MS / 1000))
        self.sink.stateChanged.connect(self._state)
        if self.mode == "pull":
            self.src = make_pull_source(self.ring)
            self.sink.start(self.src)
            self.io = None
        else:
            self.io = self.sink.start()
        self.log(f"audio: opened '{self.dev_desc}' mode={self.mode} buffer={self.sink.bufferSize()} B")

    def _teardown(self):
        s, self.sink, self.io = self.sink, None, None
        if s is not None:
            try:
                s.stateChanged.disconnect(self._state)
            except (RuntimeError, TypeError):
                pass
            s.stop()
        if self.src is not None:
            self.src.close()
            self.src = None

    def _state(self, st):
        from PySide6.QtMultimedia import QAudio
        if self.sink is None:
            return
        err = self.sink.error()
        if st == QAudio.State.IdleState:
            self.idle_events += 1                       # the sink ran dry (push mode) — an underrun
            if self.mode == "push":
                self.ring.note_push_starved(1)
        if err != QAudio.Error.NoError and st == QAudio.State.StoppedState and not self.closed:
            self.errors += 1
            self.last_error = str(err)
            self.log(f"audio: sink stopped with {err}; restarting in {RESTART_S:g} s")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(int(RESTART_S * 1000), self.restart)

    def _outputs_changed(self):
        if self.closed:
            return
        try:
            _open_device(self.device_id, self.excluded)
        except OSError:
            self.log("audio: no permitted output any more (unplugged?)")
            return
        from PySide6.QtMultimedia import QAudio
        if self.sink is None or self.sink.state() == QAudio.State.StoppedState:
            self.restart()

    def restart(self):
        if self.closed:
            return
        self._teardown()
        try:
            self._open()
            self.restarts += 1
        except OSError as exc:
            self.last_error = str(exc)
            self.log(f"audio: reopen failed: {exc}")

    def _pump(self):
        """Push mode only: write what the sink can take; keep the rest in the ring (no data loss)."""
        if self.io is None or self.sink is None:
            return
        free = self.sink.bytesFree() // 4
        if free <= 0:
            return
        a = self.ring.pull(free, pad=False)
        if not len(a):
            return
        n = self.io.write(a.tobytes())
        n = max(0, int(n)) // 4
        self.bytes_written += 4 * n
        if n < len(a):
            self.partial_writes += 1
            self.ring.unread(a[n:])

    def write(self, audio):
        """Legacy API: queue audio (thread-safe). Never writes to Qt from the caller's thread."""
        self.ring.push(audio)

    def stats(self):
        d = {"mode": self.mode, "device": getattr(self, "dev_desc", None), "sink_errors": self.errors,
             "sink_restarts": self.restarts, "sink_idle_events": self.idle_events,
             "partial_writes": self.partial_writes, "last_error": self.last_error}
        if self.sink is not None:
            d["sink_buffer_bytes"] = self.sink.bufferSize()
            d["sink_bytes_free"] = self.sink.bytesFree()
            d["sink_buffer_ms"] = round(1000.0 * self.sink.bufferSize() / (4 * self.rate), 1)
        return d

    def close(self):
        self.closed = True
        self.pump.stop()
        self._teardown()
