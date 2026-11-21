# T.A.S.K. status cards (schema 1)

Each comms module writes `$XDG_RUNTIME_DIR/task/status/<module>.json` (dir 0700, file 0600, atomic replace)
via `task_comms.status.StatusWriter`. The launcher only reads them.

| key | type | meaning |
|---|---|---|
| schema | int | 1 |
| module | str | `task-mesh`, `task-aprs`, `task-sdr` |
| state | str | starting, disconnected, connecting, connected, rx-only, tx-capable, queued, busy, error, stopped |
| device | str/null | human label of the device in use |
| summary | str | ≤120 chars, never message content |
| counts | {str:int} | counters only |
| last_error | str/null | ≤200 chars |
| indicators | [str] | e.g. `QUEUED` (APRS: frame waiting in Direwolf's queue). There is no ON-AIR indicator: T.A.S.K. cannot observe RF |
| pid, heartbeat_ts | int, float | card is *stale* after 10 s without heartbeat, *dead* if the pid is gone |

Never contained: message text, PSKs, tokens, passwords, station lists.
