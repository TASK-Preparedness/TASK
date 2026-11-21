# task-geofeed/1

Producer file: `$XDG_DATA_HOME/task-comms/feeds/<producer>.sqlite` (dir 0700, file 0600, WAL, one writer).

```sql
meta(key TEXT PRIMARY KEY, value TEXT)   -- schema=1, producer, updated_ts
entity(id TEXT PRIMARY KEY, layer TEXT, label TEXT, lat REAL, lon REAL, alt_m REAL, accuracy_m REAL,
       observed_ts INTEGER, source TEXT, kind TEXT, stale_after_s INTEGER, attrs_json TEXT)
```

* `kind` is `observed` (position heard/reported) or `inferred`; nothing fabricated, unknown = NULL.
* `source` e.g. `aprs-rf`, `aprs-is` (third-party, labelled), `mesh`, `gmrs-radio`.
* Readers (task-maps) open `file:…?mode=ro`, poll `meta.updated_ts`; missing/corrupt file = empty layer.
* Mesh positions are written only while the user enables "Show mesh nodes on Maps".
