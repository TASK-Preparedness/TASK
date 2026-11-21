-- T.A.S.K. Mesh Operations schema v1 (design report §6.2).
-- PRAGMA auto_vacuum = INCREMENTAL is applied by the migrator before this file runs on a new DB.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    checksum    TEXT    NOT NULL,           -- sha256 of the migration file; mismatch = refuse to start (dev error)
    applied_at  INTEGER NOT NULL            -- Pi clock, epoch s
) STRICT;

-- Local radios we have connected to (identity learned after handshake)
CREATE TABLE radios (
    node_num          INTEGER PRIMARY KEY,  -- myInfo.my_node_num
    node_id           TEXT,                 -- '!a1b2c3d4'
    long_name         TEXT,
    short_name        TEXT,
    hw_model          TEXT,                 -- enum name e.g. 'HELTEC_V3'
    firmware_version  TEXT,                 -- metadata.firmware_version, NULL if not reported
    usb_vid           INTEGER, usb_pid INTEGER, usb_serial TEXT,
    last_port_by_id   TEXT, last_port_by_path TEXT, last_port_dev TEXT,
    first_connected   INTEGER NOT NULL,
    last_connected    INTEGER NOT NULL
) STRICT;

-- Current best-known state per mesh node. Every radio-derived column is NULLable: NULL = unknown = '—'.
CREATE TABLE nodes (
    node_num              INTEGER PRIMARY KEY,
    node_id               TEXT,
    long_name             TEXT,
    short_name            TEXT,
    hw_model              TEXT,
    role                  TEXT,
    is_licensed           INTEGER CHECK (is_licensed IN (0,1)),
    last_heard_radio      INTEGER,          -- epoch from the RADIO clock (nodeDB lastHeard / packet rxTime)
    last_rx_local         INTEGER,          -- epoch from the PI clock when we last observed a packet from it
    snr                   REAL,
    snr_source            TEXT CHECK (snr_source IN ('radio_nodedb','packet')),
    rssi_last             INTEGER,          -- dBm, from last packet rxRssi only
    rssi_at_local         INTEGER,
    hops_away             INTEGER,
    hops_source           TEXT CHECK (hops_source IN ('radio_nodedb','calculated')),
    battery_level         INTEGER,          -- raw 0..100, >100 = powered
    voltage               REAL,
    latitude              REAL CHECK (latitude  BETWEEN -90  AND 90),
    longitude             REAL CHECK (longitude BETWEEN -180 AND 180),
    altitude_m            INTEGER,
    position_time_radio   INTEGER,
    position_precision_bits INTEGER,
    via_mqtt              INTEGER CHECK (via_mqtt IN (0,1)),
    heard_via_radio       INTEGER REFERENCES radios(node_num) ON DELETE SET NULL,
    first_seen_local      INTEGER NOT NULL,
    updated_local         INTEGER NOT NULL
) STRICT;
CREATE INDEX nodes_last_rx ON nodes(last_rx_local);

-- Append-only per-packet link observations (RSSI/SNR history; future coverage maps). Pruned by retention.
CREATE TABLE node_observations (
    id               INTEGER PRIMARY KEY,
    node_num         INTEGER NOT NULL REFERENCES nodes(node_num) ON DELETE CASCADE,
    radio_num        INTEGER REFERENCES radios(node_num) ON DELETE SET NULL,
    observed_local   INTEGER NOT NULL,
    rx_time_radio    INTEGER,
    rx_snr           REAL,
    rx_rssi          INTEGER,
    hop_start        INTEGER,
    hop_limit        INTEGER,
    portnum          TEXT,                  -- 'POSITION_APP', 'TELEMETRY_APP', ...
    via_mqtt         INTEGER CHECK (via_mqtt IN (0,1)),
    packet_id        INTEGER
) STRICT;
CREATE INDEX node_obs_node_time ON node_observations(node_num, observed_local);
CREATE INDEX node_obs_time      ON node_observations(observed_local);

-- Connection state machine history (what the operator needs after an incident)
CREATE TABLE connection_events (
    id            INTEGER PRIMARY KEY,
    at_local      INTEGER NOT NULL,
    from_state    TEXT,
    to_state      TEXT    NOT NULL,
    reason        TEXT,                     -- 'hotplug_remove', 'EACCES', 'handshake_timeout', ...
    port_dev      TEXT, port_by_id TEXT, port_by_path TEXT,
    usb_vid       INTEGER, usb_pid INTEGER, usb_serial TEXT,
    radio_num     INTEGER REFERENCES radios(node_num) ON DELETE SET NULL
) STRICT;
CREATE INDEX conn_events_time ON connection_events(at_local);

-- Sanitised radio/app events: bad packets, errors, device notifications. NEVER raw packets with keys.
CREATE TABLE radio_events (
    id          INTEGER PRIMARY KEY,
    at_local    INTEGER NOT NULL,
    level       TEXT NOT NULL CHECK (level IN ('DEBUG','INFO','NOTICE','WARNING','ERROR','CRITICAL')),
    kind        TEXT NOT NULL,              -- 'bad_packet','device_log','client_notification','serial_error',...
    message     TEXT NOT NULL,
    detail_json TEXT CHECK (detail_json IS NULL OR json_valid(detail_json)),
    radio_num   INTEGER REFERENCES radios(node_num) ON DELETE SET NULL
) STRICT;
CREATE INDEX radio_events_time ON radio_events(at_local);
