# Benchmarks

This page shows measured performance characteristics of
`ThreadPoolXMLRPCServer` compared to `SimpleXMLRPCServer`.

---

## Methodology

The benchmark script at `benchmarks/benchmark_server.py` runs both servers
against an identical workload:

- A pool of N concurrent client threads each sends M sequential XML-RPC calls
- Two method profiles: **fast** (CPU-only, no sleep) and **slow** (simulates
  I/O-bound work with `time.sleep`)
- The slow profile is more representative of real workloads (database queries,
  network calls, file I/O)

### Run it yourself

```console
# Default: 200 requests, 8 concurrent clients, 20 ms I/O simulation
python benchmarks/benchmark_server.py

# Heavier load
python benchmarks/benchmark_server.py --requests 400 --clients 8 --sleep 0.05
```

Full options:

```
--requests INT   Total requests per server (default: 200)
--clients  INT   Concurrent client threads (default: 8)
--sleep    FLOAT Simulated I/O delay per request in seconds (default: 0.02)
--workers  INT   max_workers for ThreadPoolXMLRPCServer (default: cpu_count)
```

---

## Results (representative run)

### Test environment

- CPU: 22-core Intel (22 logical CPUs reported by `os.cpu_count()`)
- Python 3.14.2
- OS: Linux
- Parameters: **400 requests, 8 concurrent clients, 50 ms sleep**

### Fast requests (no I/O simulation)

| Server | RPS | Mean latency | p95 | p99 |
|--------|-----|-------------|-----|-----|
| `SimpleXMLRPCServer` | 366 | 8.6 ms | 5.4 ms | 9.7 ms |
| `ThreadPoolXMLRPCServer` | 1 132 | 6.9 ms | 9.7 ms | 11.5 ms |

With fast (CPU-bound) requests and 8 clients both servers perform similarly
because `SimpleXMLRPCServer`'s one-request-at-a-time model is not a bottleneck
when requests finish quickly.

### Slow requests (50 ms simulated I/O)

| Server | RPS | Mean latency | p95 | p99 |
|--------|-----|-------------|-----|-----|
| `SimpleXMLRPCServer` | 19 | 394 ms | 371 ms | 2 369 ms |
| `ThreadPoolXMLRPCServer` | 148 | 54 ms | 58 ms | 63 ms |

**ThreadPoolXMLRPCServer delivers ~7.8× more throughput** and reduces mean
latency from 394 ms to 54 ms when requests block on I/O.

### Throughput comparison (bar chart)

```
Slow requests — RPS (higher is better)

SimpleXMLRPCServer    ██ 19
ThreadPoolXMLRPCServer ██████████████████████████████████████████████████████████████████████████████ 148
```

```
Slow requests — Mean latency in ms (lower is better)

SimpleXMLRPCServer    ███████████████████████████████████████████████████████████████████████████ 394 ms
ThreadPoolXMLRPCServer ██████████ 54 ms
```

---

## Interpretation

The key insight is that `SimpleXMLRPCServer` is **single-threaded at the
application level**: while one request is waiting for I/O, all other clients
queue at the OS TCP level. `ThreadPoolXMLRPCServer` runs up to `max_workers`
requests concurrently, so I/O wait time overlaps.

The improvement grows with:

- **higher request latency** (more I/O overlap possible)
- **more concurrent clients** (more parallelism to exploit)
- **lower CPU utilisation per request** (threads aren't blocked by the GIL)

The improvement plateaus at:

- `max_workers` threads with fully CPU-bound work (GIL contention)
- network bandwidth / server-socket throughput limits

---

## Overload policy benchmarks

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

## XMLRPCASGIApp benchmarks

`XMLRPCASGIApp` is measured **in-process** using `httpx.ASGITransport`
(no TCP overhead), so results reflect pure XML-RPC parse/dispatch/marshal cost
plus handler execution time.

### Run it yourself

```console
# Default: 500 requests, 20 concurrent, 10 ms sleep
python benchmarks/benchmark_asgi.py

# Custom load
python benchmarks/benchmark_asgi.py --requests 1000 --concurrency 50 --sleep 0.005
```

Full options:

```
--requests    INT   Total requests per scenario (default: 500)
--concurrency INT   Max concurrent in-flight requests (default: 20)
--sleep       FLOAT Handler sleep time in seconds (default: 0.01)
--workers     INT   Thread-pool size for sync handlers (default: 8)
```

### Results (representative run)

#### Test environment

- CPU: 22-core Intel (Linux)
- Python 3.14.2
- Parameters: **500 requests, 20 concurrency, 10 ms sleep, 8 workers**

#### Scenario results

| Handler type | RPS | p50 latency | p95 latency | p99 latency |
|---|---|---|---|---|
| `async def` (asyncio.sleep) | **1 647** | 11.2 ms | 13.9 ms | 15.0 ms |
| sync (time.sleep, thread pool) | 744 | 26.5 ms | 28.2 ms | 29.1 ms |
| instant (no sleep) | **1 923** | 7.0 ms | 12.0 ms | 16.5 ms |

#### Throughput comparison

```
Requests/second (higher is better)

async  (asyncio.sleep)  ████████████████████████████████████████████████████████ 1647
sync   (time.sleep)     █████████████████████████▌ 744
instant (no sleep)      ████████████████████████████████████████████████████████████████████ 1923
```

#### Latency comparison — p50 (lower is better)

```
p50 latency in ms (lower is better)

async  (asyncio.sleep)  ███████████▌ 11.2 ms
sync   (time.sleep)     ██████████████████████████▌ 26.5 ms
instant (no sleep)      ███████ 7.0 ms
```

### Interpretation

**`async def` handlers** run directly in the asyncio event loop.  With
`concurrency=20` and `sleep=10 ms`, 20 async coroutines overlap their
`asyncio.sleep` calls, giving ~1 650 RPS.

**Sync handlers** run in the `ThreadPoolExecutor`.  With `max_workers=8` and
20 concurrent requests, only 8 can execute in parallel — the other 12 queue,
raising p50 latency to ~26 ms and halving throughput compared to async.
Increasing `max_workers` to 20 would match async performance here.

**Instant handlers** (no sleep) show the XML-RPC overhead floor: ~0.5 ms per
request for UTF-8 parse + method dispatch + response marshal.

### Key takeaways

- Prefer `async def` handlers for I/O-bound work — they fully exploit the
  event loop and bypass the thread pool entirely.
- Match `max_workers` to your concurrency level for sync handlers; a good
  rule of thumb is `max_workers ≈ expected_concurrent_sync_requests`.
- The XML-RPC parse/marshal overhead is ~0.5 ms per call (negligible for most
  workloads; use `use_builtin_types=True` for datetime / bytes-heavy APIs).
