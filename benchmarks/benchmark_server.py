"""Benchmark: SimpleXMLRPCServer vs ThreadPoolXMLRPCServer.

Measures throughput (requests/second) under three scenarios:
  - fast   : handler returns immediately
  - slow   : handler sleeps to simulate I/O-bound work
  - mixed  : half fast, half slow requests sent concurrently

Usage::

    python benchmarks/benchmark_server.py [--requests N] [--clients N] [--sleep S]

Interpretation notes
--------------------
- ThreadPoolXMLRPCServer excels when handlers block (slow/mixed scenario).
- For purely CPU-bound workloads the GIL limits parallelism; use
  multiprocessing via xmlrpc_extended.multiprocess in that case.
- Results vary with hardware, OS scheduler, and Python version.
  Always benchmark under conditions representative of your workload.
"""

from __future__ import annotations

import argparse
import statistics
import threading
import time
import xmlrpc.client
import xmlrpc.server
from collections.abc import Generator
from contextlib import contextmanager

from xmlrpc_extended import ServerOverloadPolicy, ThreadPoolXMLRPCServer

# ---------------------------------------------------------------------------
# Shared handler functions
# ---------------------------------------------------------------------------


def fast_handler(x: int) -> int:
    """Return immediately — CPU-minimal handler."""
    return x + 1


def slow_handler(x: int, sleep: float = 0.05) -> int:
    """Sleep to simulate I/O-bound work."""
    time.sleep(sleep)
    return x + 1


# ---------------------------------------------------------------------------
# Server context managers
# ---------------------------------------------------------------------------


@contextmanager
def _simple_server() -> Generator[str, None, None]:
    server = xmlrpc.server.SimpleXMLRPCServer(
        ("127.0.0.1", 0),
        logRequests=False,
        allow_none=True,
    )
    server.register_function(fast_handler, "fast")
    server.register_function(slow_handler, "slow")
    t = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=2)


@contextmanager
def _pool_server(max_workers: int = 8) -> Generator[str, None, None]:
    server = ThreadPoolXMLRPCServer(
        ("127.0.0.1", 0),
        max_workers=max_workers,
        max_pending=max_workers * 4,
        overload_policy=ServerOverloadPolicy.BLOCK,
        logRequests=False,
        allow_none=True,
    )
    server.register_function(fast_handler, "fast")
    server.register_function(slow_handler, "slow")
    t = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=2)


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------


def run_scenario(
    url: str,
    *,
    method: str,
    num_clients: int,
    num_requests: int,
    sleep: float,
) -> dict[str, float]:
    """Send requests from *num_clients* threads; return timing stats."""
    latencies: list[float] = []
    lock = threading.Lock()
    errors = 0

    def worker() -> None:
        nonlocal errors
        proxy = xmlrpc.client.ServerProxy(url, allow_none=True)
        for _ in range(num_requests // num_clients):
            t0 = time.perf_counter()
            try:
                if method == "fast":
                    proxy.fast(1)
                else:
                    proxy.slow(1, sleep)
            except Exception:
                with lock:
                    errors += 1
                continue
            with lock:
                latencies.append(time.perf_counter() - t0)

    threads = [threading.Thread(target=worker) for _ in range(num_clients)]
    wall_start = time.perf_counter()
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    wall = time.perf_counter() - wall_start

    n = len(latencies)
    return {
        "requests_sent": n,
        "errors": errors,
        "wall_s": round(wall, 3),
        "rps": round(n / wall, 1) if wall > 0 else 0,
        "mean_ms": round(statistics.mean(latencies) * 1000, 2) if latencies else 0,
        "p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95)] * 1000, 2) if latencies else 0,
        "p99_ms": round(sorted(latencies)[int(len(latencies) * 0.99)] * 1000, 2) if latencies else 0,
    }


def print_row(label: str, stats: dict[str, float]) -> None:
    print(
        f"  {label:<28} reqs={stats['requests_sent']:>5}  "
        f"rps={stats['rps']:>8.1f}  "
        f"mean={stats['mean_ms']:>7.2f}ms  "
        f"p95={stats['p95_ms']:>7.2f}ms  "
        f"p99={stats['p99_ms']:>7.2f}ms  "
        f"errors={stats['errors']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="xmlrpc_extended benchmark")
    parser.add_argument("--requests", type=int, default=200, help="Total requests per scenario")
    parser.add_argument("--clients", type=int, default=8, help="Concurrent client threads")
    parser.add_argument("--sleep", type=float, default=0.02, help="Slow handler sleep (seconds)")
    parser.add_argument("--workers", type=int, default=8, help="ThreadPoolXMLRPCServer max_workers")
    args = parser.parse_args()

    print(f"\nBenchmark: {args.requests} requests, {args.clients} clients, sleep={args.sleep}s\n")
    print(f"{'Server':<28}  {'Method':<6}  rps        mean       p95        p99        errors")
    print("-" * 90)

    scenarios = [
        ("fast", "fast"),
        ("slow", "slow"),
    ]

    with _simple_server() as simple_url, _pool_server(max_workers=args.workers) as pool_url:
        for label, method in scenarios:
            stats_simple = run_scenario(
                simple_url,
                method=method,
                num_clients=args.clients,
                num_requests=args.requests,
                sleep=args.sleep,
            )
            print_row(f"SimpleXMLRPCServer   [{label}]", stats_simple)

            stats_pool = run_scenario(
                pool_url,
                method=method,
                num_clients=args.clients,
                num_requests=args.requests,
                sleep=args.sleep,
            )
            print_row(f"ThreadPoolXMLRPCServer [{label}]", stats_pool)
            print()

    print("Done.")


if __name__ == "__main__":
    main()
