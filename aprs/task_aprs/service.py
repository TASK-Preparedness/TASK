# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-aprs runtime: connects to an already running Direwolf (AGW preferred, KISS fallback), receives,
runs the amateur and GMRS controllers and writes the status card. Starts with transmit idle: nothing is
ever sent at start-up."""

import threading
import time

from task_comms import paths
from task_comms.audit import AuditLog
from task_comms.feeds import FeedWriter
from task_comms.status import StatusWriter
from task_comms.txpolicy import AmateurRadio, TxPolicy

from task_aprs import config, dwconf
from task_aprs.agw import AgwClient
from task_aprs.amateur import AmateurTx
from task_aprs.gmrs.service import GmrsTx
from task_aprs.kiss import KissClient
from task_aprs.rx import Receiver


class AprsService:
    def __init__(self, session_role=lambda: None, conf_root=None, state_root=None, dw_conf=None,
                 status_dir=None, feed_dir=None, clock=time.monotonic, wall=time.time, gmrs_driver=None,
                 agw_factory=AgwClient, kiss_factory=KissClient):
        self.role = session_role
        self.conf_root = conf_root
        state = state_root or paths.state_dir("task-aprs")
        self.dw = dw_conf if dw_conf is not None else dwconf.load()
        self.amateur_cfg = config.load_amateur(conf_root)
        self.gmrs_cfg = config.load_gmrs(conf_root)
        self.profiles = config.load_profiles("amateur", conf_root)
        self.gmrs_profiles = config.load_profiles("gmrs", conf_root)
        self.selected = self.profiles[0].id if self.profiles else None
        self.gmrs_selected = self.gmrs_profiles[0].id if self.gmrs_profiles else None
        self.status = StatusWriter("task-aprs", status_dir, clock=wall)
        self.feed = FeedWriter("task-aprs", feed_dir, clock=wall)
        self.policy = TxPolicy(clock)
        self.gmrs_policy = TxPolicy(clock)          # separate rate/duplicate state for GMRS
        self.transport = None
        self.agw_factory, self.kiss_factory = agw_factory, kiss_factory
        self.listeners = []
        self.rx = Receiver(self.feed, wall, on_packet=self._on_packet)
        self.amateur = AmateurTx(self.policy, AuditLog(state / "audit-amateur.jsonl"), lambda: self.transport,
                                 lambda: self.amateur_cfg, self.radio, self.role, clock, self._changed)
        self.gmrs_driver = gmrs_driver
        self.gmrs = GmrsTx(self.gmrs_policy, AuditLog(state / "audit-gmrs.jsonl"), lambda: self.gmrs_driver,
                           lambda: self.gmrs_cfg, self.gmrs_profile, self.role, clock, self.feed)
        if gmrs_driver is not None:
            gmrs_driver.set_receive_callback(self.gmrs.handle_receive)
        self._lock = threading.RLock()
        self.last_error = None

    # ------------------------------------------------------------ profiles
    def profile(self):
        return next((p for p in self.profiles if p.id == self.selected), None)

    def gmrs_profile(self):
        return next((p for p in self.gmrs_profiles if p.id == self.gmrs_selected), None)

    def radio(self):
        p = self.profile()
        if p is None:
            return None
        return AmateurRadio(p.id, verified=p.verified, ptt_configured=bool(self.dw.channel(p.channel).ptt),
                            channel=p.channel)

    # ------------------------------------------------------------ connection
    def connect(self):
        self.disconnect()
        errors = []
        agw = self.dw.effective_agw_port
        if agw:
            try:
                self.transport = self.agw_factory(port=agw, on_frame=self._on_frame, on_close=self._on_close).connect()
                self.transport.enable_raw_rx()
            except OSError as exc:
                errors.append(f"AGW {agw}: {exc}")
                self.transport = None
        if self.transport is None:
            for port in self.dw.effective_kiss_ports:
                try:
                    self.transport = self.kiss_factory(port=port, on_frame=self._on_frame,
                                                       on_close=self._on_close).connect()
                    break
                except OSError as exc:
                    errors.append(f"KISS {port}: {exc}")
        self.last_error = "; ".join(errors) if self.transport is None else None
        self.write_status()
        return self.transport is not None

    def disconnect(self):
        t, self.transport = self.transport, None
        if t:
            t.close()

    def _on_close(self):
        self.transport = None
        self.last_error = "Direwolf connection closed"
        self.write_status()
        self._changed(None)

    def _on_frame(self, channel, raw):
        with self._lock:
            self.rx.handle(channel, raw, self.amateur_cfg.callsign)

    def _on_packet(self, frame, packet, via):
        if via == "RF":
            self.amateur.on_packet(frame, packet)
        self._changed(packet)

    def _changed(self, obj):
        for cb in list(self.listeners):
            cb(obj)

    # ------------------------------------------------------------ periodic
    def tick(self):
        with self._lock:
            self.amateur.tick()
        self.write_status()

    def write_status(self):
        if self.transport is None:
            state, summary = "disconnected", "Direwolf not connected"
        else:
            tx_ready = self.amateur_cfg.tx_enabled and self.radio() is not None and self.radio().verified
            state = "queued" if self.amateur.queued() else ("tx-capable" if tx_ready else "rx-only")
            summary = f"Direwolf {self.transport.name.split('-')[1].upper()} · {len(self.rx.stations)} stations"
        self.status.write(state, device="Direwolf", summary=summary,
                          counts={"frames": self.rx.frames, "stations": len(self.rx.stations)},
                          last_error=self.last_error, indicators=["QUEUED"] if self.amateur.queued() else [])

    def close(self):
        self.disconnect()
        if self.gmrs_driver is not None:
            self.gmrs_driver.close()
        self.status.write("stopped", summary="task-aprs closed")
        self.feed.close()
