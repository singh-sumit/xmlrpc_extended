# xmlrpc_extended

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

`xmlrpc_extended` is a small, dependency-light package that upgrades Python's
stdlib XML-RPC server with bounded thread-pool concurrency and explicit overload
handling.

## Current package scope

- `ThreadPoolXMLRPCServer` for drop-in `SimpleXMLRPCServer` style usage
- bounded worker and pending-request limits
- overload policies: block, close, or XML-RPC fault
- graceful executor shutdown
- request body size limiting through `LimitedXMLRPCRequestHandler`
- `max_pending` counts queued requests beyond the active worker pool; total
  outstanding capacity is `max_workers + max_pending`

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

### Recommended defaults

| Deployment | Suggested settings |
|------------|--------------------|
| Embedded / internal tool | `max_workers=4`, `max_pending=None` (= 4), `BLOCK` |
| Service with SLA | `max_workers=N`, `max_pending=0`, `FAULT` or `CLOSE` |
| Behind a load balancer | `max_workers=N`, `max_pending=small`, `CLOSE` |

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

## Security notes

- XML-RPC from the Python stdlib is not suitable for untrusted public networks.
- Prefer localhost/private-network deployment behind authentication and TLS
  termination.
- Use `max_request_size` to reject oversized payloads early.
- Avoid exposing dotted-name instance traversal on insecure networks.

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

- worker-process helpers and `SO_REUSEPORT` support
- optional async/ASGI integration
- richer operational metrics and examples
