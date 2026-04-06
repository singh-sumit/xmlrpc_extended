# Observability — Server Stats

`ThreadPoolXMLRPCServer.stats()` returns a **thread-safe, point-in-time
snapshot** of internal activity counters as a `ServerStats` frozen dataclass.

---

## Reading stats

```python
snap = server.stats()
print(f"active={snap.active} queued={snap.queued} completed={snap.completed}")
```

`stats()` acquires a single lock and copies the counters, so it is safe to call
from any thread including from a registered RPC method.

---

## Counter reference

| Field | Type | Description |
|-------|------|-------------|
| `active` | `int` | Requests currently executing in worker threads |
| `queued` | `int` | Requests submitted to the thread pool but not yet started |
| `rejected_close` | `int` | Cumulative rejections via the `CLOSE` policy |
| `rejected_fault` | `int` | Cumulative rejections via the `FAULT` policy |
| `rejected_503` | `int` | Cumulative rejections via the `HTTP_503` policy |
| `completed` | `int` | Cumulative requests that finished without a transport error |
| `errored` | `int` | Cumulative requests where an unhandled exception escaped the worker |

!!! note "completed vs errored"
    `completed` is incremented when the worker finishes — **even if the
    XML-RPC method raised an exception**, because the dispatcher catches
    application exceptions and converts them to XML-RPC faults which are still
    sent as valid `200 OK` responses. `errored` is only incremented when a
    low-level transport error occurs (e.g. a broken socket after a response was
    partially sent).

---

## Exposing stats as an RPC method

```python
import dataclasses

def rpc_stats() -> dict:
    return dataclasses.asdict(server.stats())

server.register_function(rpc_stats, "server.stats")
```

---

## Periodic logging example

```python
import threading

def _log_stats(interval: float = 10.0) -> None:
    while True:
        s = server.stats()
        print(
            f"active={s.active} queued={s.queued} "
            f"completed={s.completed} errored={s.errored} "
            f"rejected_close={s.rejected_close} "
            f"rejected_fault={s.rejected_fault} "
            f"rejected_503={s.rejected_503}"
        )
        threading.Event().wait(interval)

threading.Thread(target=_log_stats, daemon=True).start()
server.serve_forever()
```

---

## Prometheus integration sketch

```python
from prometheus_client import Gauge, Counter, start_http_server

ACTIVE    = Gauge("xmlrpc_active_requests", "Concurrently executing")
QUEUED    = Gauge("xmlrpc_queued_requests",  "Waiting for a worker slot")
COMPLETED = Counter("xmlrpc_completed_total", "Successfully finished")
ERRORED   = Counter("xmlrpc_errored_total",   "Failed with transport error")

def _scrape() -> None:
    while True:
        s = server.stats()
        ACTIVE.set(s.active)
        QUEUED.set(s.queued)
        # Counters must only go up — track delta
        threading.Event().wait(5)

start_http_server(9090)
threading.Thread(target=_scrape, daemon=True).start()
server.serve_forever()
```

!!! tip
    The snapshot is cheap (one lock acquisition + 7 integer reads) and safe to
    call every second or faster.
