# xmlrpc_extended

[![CI](https://github.com/singh-sumit/xmlrpc_extended/actions/workflows/ci.yml/badge.svg)](https://github.com/singh-sumit/xmlrpc_extended/actions/workflows/ci.yml)
[![Docs](https://github.com/singh-sumit/xmlrpc_extended/actions/workflows/docs.yml/badge.svg)](https://singh-sumit.github.io/xmlrpc_extended/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Discussions](https://img.shields.io/badge/Discussions-GitHub-brightgreen)](https://github.com/singh-sumit/xmlrpc_extended/discussions)

**[📖 Full documentation](https://singh-sumit.github.io/xmlrpc_extended/)** · [Issues](https://github.com/singh-sumit/xmlrpc_extended/issues) · [Discussions](https://github.com/singh-sumit/xmlrpc_extended/discussions)

`xmlrpc_extended` is a small, dependency-light package that upgrades Python's
stdlib XML-RPC server with bounded thread-pool concurrency and explicit overload
handling.

## Current package scope

- `ThreadPoolXMLRPCServer` — drop-in `SimpleXMLRPCServer` replacement with a bounded `ThreadPoolExecutor`
- bounded worker and pending-request limits with configurable overload policies (block, close, fault, HTTP 503)
- graceful executor shutdown
- request body size limiting through `LimitedXMLRPCRequestHandler`
- `max_pending` counts queued requests beyond the active worker pool; total outstanding capacity is `max_workers + max_pending`
- `XMLRPCClient` context manager with configurable timeout
- `SO_REUSEPORT` scale-out helpers for Linux (`xmlrpc_extended.multiprocess`)
- `XMLRPCASGIApp` — ASGI 3 adapter; deploy on uvicorn/hypercorn/granian with `async def` and sync handlers

## Quickstart

```python
from xmlrpc_extended import ServerOverloadPolicy, ThreadPoolXMLRPCServer


def add(left, right):
    return left + right


server = ThreadPoolXMLRPCServer(
    ("127.0.0.1", 8000),
    max_workers=8,
    max_pending=16,
    overload_policy=ServerOverloadPolicy.FAULT,
    logRequests=False,
)
server.register_introspection_functions()
server.register_function(add, "add")
server.serve_forever()
```

With `max_workers=8, max_pending=16`, up to 8 requests run concurrently and up
to 16 additional requests may wait for a worker. After that, the configured
overload policy is applied.

## Overload semantics and queueing model

### Capacity model

```
total outstanding capacity = max_workers + max_pending
```

| Parameter | Role |
|-----------|------|
| `max_workers` | Maximum requests executing concurrently in the thread pool |
| `max_pending` | Maximum requests waiting for a free worker slot |
| `request_queue_size` | OS-level TCP accept backlog (before the application sees the request) |

**Default:** `max_pending=None` resolves to `max_workers`, so by default the total capacity is `2 × max_workers`. For latency-sensitive deployments set `max_pending=0` to fail fast instead of queuing.

### Overload policy behavior

| Policy | What happens when capacity is exhausted |
|--------|----------------------------------------|
| `BLOCK` (default) | The accept thread blocks until a worker slot opens. Requests queue at the OS level. Suitable for trusted, low-variance load. |
| `CLOSE` | The connection is closed immediately without sending a response. The client receives a connection-reset error. Suitable for shedding load fast. |
| `FAULT` | An XML-RPC fault response is returned with the configured `overload_fault_code` and `overload_fault_string`. Clients that speak XML-RPC can distinguish overload from method errors. |
| `HTTP_503` | An HTTP `503 Service Unavailable` response is returned. Non-XML-RPC clients (e.g. HTTP health-checkers) can detect overload at the transport layer. |

### Recommended defaults

| Deployment | Suggested settings |
|------------|--------------------|
| Embedded / internal tool | `max_workers=4`, `max_pending=None` (= 4), `BLOCK` |
| Service with SLA | `max_workers=N`, `max_pending=0`, `FAULT` or `HTTP_503` |
| Behind a load balancer | `max_workers=N`, `max_pending=small`, `CLOSE` or `HTTP_503` |

## Restricting accepted URL paths

By default the server accepts XML-RPC requests at `/` and `/RPC2`. Restrict this with `rpc_paths`:

```python
server = ThreadPoolXMLRPCServer(
    ("127.0.0.1", 8000),
    rpc_paths=("/rpc",),  # only /rpc is accepted; all others return 404
)
```

## Observability — server stats

`ThreadPoolXMLRPCServer.stats()` returns a `ServerStats` snapshot with the following counters:

| Field | Meaning |
|-------|---------|
| `active` | Requests currently executing in worker threads |
| `queued` | Requests submitted to the thread pool but not yet running |
| `rejected_close` | Requests rejected with connection close (CLOSE policy) |
| `rejected_fault` | Requests rejected with fault response (FAULT policy) |
| `rejected_503` | Requests rejected with HTTP 503 (HTTP_503 policy) |
| `completed` | Requests that finished successfully |
| `errored` | Requests that raised an exception in the handler |

```python
snap = server.stats()
print(f"active={snap.active} queued={snap.queued} completed={snap.completed}")
```

## Client helpers

`xmlrpc_extended.client` provides `XMLRPCClient`, a context-manager wrapper with an explicit timeout:

```python
from xmlrpc_extended.client import XMLRPCClient

with XMLRPCClient("http://127.0.0.1:8000/", timeout=5.0) as proxy:
    result = proxy.add(1, 2)
```

The default timeout is **30 seconds**. Retrying failed requests is the caller's responsibility — XML-RPC methods are not necessarily idempotent.

## Scale-out with SO_REUSEPORT (Linux only)

On Linux, multiple server processes can share the same port using `SO_REUSEPORT`:

```python
from xmlrpc_extended.multiprocess import create_reuseport_socket, spawn_workers
from xmlrpc_extended import ThreadPoolXMLRPCServer

def run_worker():
    sock = create_reuseport_socket("0.0.0.0", 8000)
    server = ThreadPoolXMLRPCServer(("0.0.0.0", 0), bind_and_activate=False)
    server.socket = sock
    server.server_activate()
    server.register_function(lambda x: x + 1, "inc")
    server.serve_forever()

if __name__ == "__main__":
    processes = spawn_workers(run_worker, num_workers=4)
    for p in processes:
        p.join()
```

See `xmlrpc_extended.multiprocess` module docs for full details.

## Development approach

This repository was bootstrapped with TDD:

1. define server behavior in integration-style tests
2. implement the public API to satisfy those tests
3. keep the package small and compatible with stdlib XML-RPC patterns

## Local validation

```bash
python -m pip install . --no-deps
python -m unittest discover -s tests -v
```

## Benchmarks

```bash
pip install .
# Thread-pool server vs stdlib SimpleXMLRPCServer
python benchmarks/benchmark_server.py --requests 200 --clients 8 --sleep 0.02
# ASGI adapter in-process benchmark
python benchmarks/benchmark_asgi.py
```

## Security

> ⚠️ `xmlrpc_extended` is not suitable for untrusted public networks. See [SECURITY.md](SECURITY.md) for the full security posture, deployment checklist, and vulnerability reporting process.

- Use `max_request_size` to reject oversized payloads early.
- Restrict URL paths with `rpc_paths`.
- Never set `allow_dotted_names=True` on handlers exposed to untrusted clients.

### Request-size and request-shape expectations

`LimitedXMLRPCRequestHandler` enforces the following rules on every incoming
POST request before any XML-RPC processing occurs:

| Condition                            | HTTP response             |
| ------------------------------------ | ------------------------- |
| `Content-Length` header missing       | `411 Length Required`     |
| `Content-Length` non-integer / negative | `400 Bad Request`       |
| `Content-Length` exceeds `max_request_size` | `413 Payload Too Large` |
| `Transfer-Encoding: chunked`         | `501 Not Implemented`     |

Only requests with a valid, non-negative `Content-Length` within the configured
limit are forwarded to the XML-RPC dispatcher. The default `max_request_size` is
**1 MiB** (1 048 576 bytes) and can be set via `ThreadPoolXMLRPCServer`'s
constructor.

## Roadmap

| Milestone | Target | Description |
|-----------|--------|-------------|
| M2 | 0.3.0 | Metrics hooks, observability examples, benchmarks ✅ |
| M3 | 0.4.0 | Multi-process / SO_REUSEPORT, HTTP 503 rejection, client helpers ✅ |
| M4 | 0.5.0 | ASGI adapter (`XMLRPCASGIApp`) ✅ |

### ASGI / async integration

`XMLRPCASGIApp` is a drop-in ASGI 3 adapter bundled with the core package (no extra install required). Deploy on any ASGI server:

```python
from xmlrpc_extended.asgi import XMLRPCASGIApp

app = XMLRPCASGIApp()

async def greet(name: str) -> str:
    return f"Hello, {name}!"

app.register_function(greet, "greet")
# uvicorn your_module:app --host 127.0.0.1 --port 8000
```

Sync handlers run in a thread pool via `asyncio.to_thread`; `async def` handlers execute directly in the event loop. See the [ASGI Integration guide](https://singh-sumit.github.io/xmlrpc_extended/user-guide/asgi/) for deployment recipes, testing patterns, and migration notes from `ThreadPoolXMLRPCServer`.
