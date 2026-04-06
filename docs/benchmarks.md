# Benchmarks

This page compares all four XML-RPC implementations shipped with this package
across two workload profiles (fast and slow/I/O-bound).

---

## Implementations compared

| Implementation | Transport | Concurrency model |
|---|---|---|
| `SimpleXMLRPCServer` | TCP loopback | Single-threaded (one request at a time) |
| `ThreadedXMLRPCServer` | TCP loopback | `ThreadingMixIn` — one OS thread per request |
| `ThreadPoolXMLRPCServer` | TCP loopback | Bounded `ThreadPoolExecutor` |
| `XMLRPCASGIApp` [async] | In-process | `async def` handlers, event-loop native |
| `XMLRPCASGIApp` [sync] | In-process | Sync handlers via `asyncio.to_thread` |

!!! note "Transport difference"
    TCP-based servers are benchmarked over a real loopback socket with
    `xmlrpc.client.ServerProxy` callers — numbers include OS scheduling + HTTP
    framing overhead.
    `XMLRPCASGIApp` is measured **in-process** via `httpx.ASGITransport` — no
    TCP stack, so numbers reflect pure XML-RPC parse/dispatch/marshal plus
    handler execution time. Real-network ASGI numbers would be ~10–15% lower.

---

## Methodology

The unified benchmark at `benchmarks/benchmark_all.py` runs all servers with:

- A pool of N concurrent client threads / coroutines, each sending M sequential requests
- **fast** profile: handler returns immediately (measures framework overhead)
- **slow** profile: handler sleeps to simulate I/O-bound work (DB, HTTP, file I/O)

### Run it yourself

```console
# Default: 160 requests, 8 concurrent clients, 20 ms I/O simulation
python benchmarks/benchmark_all.py

# Heavier load (used for the results below)
python benchmarks/benchmark_all.py --requests 320 --clients 8 --sleep 0.05
```

Full options:

```
--requests INT   Total requests per scenario (default: 160)
--clients  INT   Concurrent clients / ASGI concurrency (default: 8)
--sleep    FLOAT Simulated I/O delay per request in seconds (default: 0.02)
--workers  INT   Thread-pool size for ThreadPool/ASGI-sync (default: 8)
```

---

## Results (representative run)

### Test environment

- CPU: 22-core Intel (Linux)
- Python: 3.14.2
- Parameters: **320 requests, 8 concurrent clients, 50 ms sleep, 8 workers**

### Fast requests (no I/O simulation)

| Implementation | RPS | Mean latency | p95 | p99 |
|---|---|---|---|---|
| `SimpleXMLRPCServer` | 295 | 9.7 ms | 5.2 ms | 6.4 ms |
| `ThreadedXMLRPCServer` | 288 | 11.4 ms | 10.0 ms | 15.9 ms |
| `ThreadPoolXMLRPCServer` | **1 392** | **5.6 ms** | 7.9 ms | 9.3 ms |

With fast (near-zero-cost) handlers, `SimpleXMLRPCServer` and
`ThreadedXMLRPCServer` are similar — the per-request thread-spawn overhead of
`ThreadedXMLRPCServer` cancels out its parallelism benefit.
`ThreadPoolXMLRPCServer` wins because it amortises thread creation across
pooled workers and processes requests in parallel.

### Slow requests (50 ms simulated I/O)

| Implementation | RPS | Mean latency | p95 | p99 |
|---|---|---|---|---|
| `SimpleXMLRPCServer` | 19 | 395 ms | 508 ms | 2 372 ms |
| `ThreadedXMLRPCServer` | 149 | 53 ms | 55.9 ms | 57.9 ms |
| `ThreadPoolXMLRPCServer` | **149** | **53 ms** | 57.2 ms | 59.3 ms |
| `XMLRPCASGIApp` async | 149 | 52.8 ms | 54.6 ms | 56.1 ms |
| `XMLRPCASGIApp` sync | 148 | 53.2 ms | 55.2 ms | 58.7 ms |

**`SimpleXMLRPCServer` delivers ~8× less throughput** once requests block on I/O.
`ThreadedXMLRPCServer`, `ThreadPoolXMLRPCServer`, and `XMLRPCASGIApp` all converge
near the theoretical maximum of 8 workers × (1 / 0.05 s) = 160 RPS because all
are limited by the same concurrency budget (8) and the same sleep duration.

### Throughput comparison — slow requests (bar chart)

```
Requests/second — slow handlers (higher is better)

SimpleXMLRPCServer         ██  19
ThreadedXMLRPCServer       ████████████████████████████████████████  149
ThreadPoolXMLRPCServer     ████████████████████████████████████████  149
XMLRPCASGIApp [async]      ████████████████████████████████████████  149
XMLRPCASGIApp [sync]       ████████████████████████████████████████  148
```

### Throughput comparison — fast requests (bar chart)

```
Requests/second — fast handlers (higher is better)

SimpleXMLRPCServer         ████████  295
ThreadedXMLRPCServer       ████████  288
ThreadPoolXMLRPCServer     ████████████████████████████████████████████████████  1 392
XMLRPCASGIApp [async fast] ████████████████████████████████████████████████████████████████████████  2 303 *
```

`*` In-process only — excludes TCP overhead.

---

## Interpretation

### Why `ThreadedXMLRPCServer` ≈ `ThreadPoolXMLRPCServer` under normal load

Under a steady 8-client workload with sufficient server resources both servers
deliver the same throughput because both run 8 requests concurrently.
The critical difference appears **under burst load**:

- `ThreadedXMLRPCServer` spawns an **unbounded** number of threads — at high
  concurrency this exhausts file descriptors and memory.
- `ThreadPoolXMLRPCServer` applies a bounded semaphore — excess requests are
  handled by the configured `overload_policy` (BLOCK, CLOSE, FAULT, HTTP_503).

### When to use each implementation

| Workload | Recommendation |
|---|---|
| CPU-bound, low concurrency | `ThreadPoolXMLRPCServer`, small `max_workers` |
| I/O-bound, known peak concurrency | `ThreadPoolXMLRPCServer` or `XMLRPCASGIApp` |
| I/O-bound, high async concurrency | `XMLRPCASGIApp` with `async def` handlers |
| Already running an ASGI framework | `XMLRPCASGIApp` |
| Linux, CPU-bound, max throughput | `xmlrpc_extended.multiprocess` (SO_REUSEPORT) |

---

## ASGI in-process baseline

```
Requests/second — in-process, no TCP (higher is better)

XMLRPCASGIApp [async slow]  ████████████████████████████████████████  149
XMLRPCASGIApp [sync  slow]  ████████████████████████████████████████  148
XMLRPCASGIApp [async fast]  ████████████████████████████████████████████████████████████████████████  2 303
```

The **async fast** result (~2 300 RPS) represents the XML-RPC parse/dispatch/marshal
floor with no handler cost — roughly **0.4 ms per call**.

---

The following shows the latency impact of different rejection policies under
saturation (all worker slots full, `max_pending=0`):

| Policy | Client-side latency (rejection) | Server-side cost |
|--------|----------------------------------|-----------------|
| `CLOSE` | ~1 ms (connection reset) | ~0.01 ms |
| `FAULT` | ~5 ms (TCP round-trip + parse) | ~0.5 ms |
| `HTTP_503` | ~3 ms (TCP round-trip + parse) | ~0.3 ms |
| `BLOCK` | N/A (queues until slot free) | negligible |

`CLOSE` is the cheapest rejection — the server just closes the socket with no
writes. `FAULT` and `HTTP_503` are more informative but slightly more expensive
because they write a response body.

---

!!! tip "Optimising for your workload"
    - **Tune `max_workers`** to roughly match `expected_rps × mean_latency_s`
      (Little's Law). For example, 100 RPS × 0.05 s = 5 workers minimum.
    - **Tune `max_pending`** to absorb burst traffic: a short queue smooths
      short spikes; `max_pending=0` rejects immediately which is better for
      SLA enforcement.
    - Run the benchmark against *your* method implementations for accurate
      results — the benchmark's `sleep()` is a proxy for real I/O.

---

## Focused ASGI benchmarks

The dedicated script `benchmarks/benchmark_asgi.py` isolates `XMLRPCASGIApp`
with higher concurrency and finer sleep granularity than the unified benchmark.

```console
# 500 requests, 20 concurrent, 10 ms sleep
python benchmarks/benchmark_asgi.py

# Custom
python benchmarks/benchmark_asgi.py --requests 1000 --concurrency 50 --sleep 0.005
```

Options: `--requests INT`, `--concurrency INT`, `--sleep FLOAT`, `--workers INT`.

Use this when you want to tune `max_workers` vs async concurrency tradeoffs for
a specific handler mix — the in-process transport removes TCP noise and focuses
on pure dispatch overhead.
