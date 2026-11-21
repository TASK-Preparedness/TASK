# T.A.S.K. Phase 4C — Communications 0.3.0

* Rebrand Rain → T.A.S.K. (task-*), with compatibility aliases: rain-core-admin (task-core-compat),
  rain-mesh transitional package, /run/rain/core.sock link.
* task-core 0.3.0: package rename and the copy-only `task-core-migrate` (journal, rollback). Runtime version 0.2.1.
* python3-task-comms 0.3.0: shared feeds/status library for the communications apps.
* task-launcher 0.3.0: tiles for APRS, SDR, Mesh and Maps; tile ids task.*; the old rain.* ids are mapped.
* task-mesh 0.2.0 (was rain-mesh): status feed, map overlay feed, renamed packaging.
* task-aprs 0.1.0 (new): two-way amateur APRS through Direwolf (AGW on loopback); messages with ack/retry;
  QUEUED indicator (never "on air"). GMRS profile with its own config, audit log and TX switch (off by
  default); simulated driver only. Real GMRS hardware is BLOCKED.
* task-sdr 0.1.0 (new): SoapySDR receiver with WFM/NFM/AM/USB/LSB, spectrum, squelch. Receive only.
* task-maps 0.1.1: optional online layers with an LRU tile cache; APRS/mesh/GMRS overlays (read-only).
* task-console 0.2.0: version bump and rebrand.
* Maintainer field is a PLACEHOLDER: T.A.S.K. Development Team <TBD-maintainer-email>.
