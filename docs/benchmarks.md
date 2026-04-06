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
