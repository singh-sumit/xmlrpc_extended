"""Benchmark: XMLRPCASGIApp vs ThreadPoolXMLRPCServer.

Compares throughput (requests/second) for three handler types:

  async_io  – ``async def`` handler with a simulated async I/O delay
                (``asyncio.sleep``); runs directly in the event loop.
  sync_pool – synchronous handler with a simulated blocking delay
                (``time.sleep``); runs in the ASGI thread pool via
                ``asyncio.to_thread``.
  instant   – zero-sleep handler for baseline throughput.

All ASGI calls are made **in-process** using :class:`httpx.ASGITransport`
(no TCP overhead) so the numbers reflect pure handler + XML-RPC dispatch
overhead.  Compare with :mod:`benchmark_server` for the TCP-stack overhead of
:class:`~xmlrpc_extended.ThreadPoolXMLRPCServer`.

Usage::

    python benchmarks/benchmark_asgi.py [--requests N] [--concurrency N] [--sleep S]

Requirements::

    pip install httpx anyio  # httpx ships ASGITransport built-in
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
import xmlrpc.client

import httpx

from xmlrpc_extended.asgi import XMLRPCASGIApp

# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def async_io_handler(x: int, sleep: float = 0.01) -> int:
    """Async I/O-bound handler — runs directly in the event loop."""
    await asyncio.sleep(sleep)
    return x + 1


def sync_pool_handler(x: int, sleep: float = 0.01) -> int:
    """Sync handler — delegated to the ASGI thread pool."""
    time.sleep(sleep)
    return x + 1


def instant_handler(x: int) -> int:
    """Zero-cost handler for baseline throughput measurement."""
    return x + 1


# ---------------------------------------------------------------------------
# Benchmark core
# ---------------------------------------------------------------------------


def _build_request_body(n: int) -> bytes:
    return xmlrpc.client.dumps((n,), "inc").encode()


async def _run_single(
    client: httpx.AsyncClient,
    body: bytes,
) -> float:
    """Send one XML-RPC request and return elapsed seconds."""
    t0 = time.perf_counter()
    resp = await client.post("/", content=body, headers={"Content-Type": "text/xml"})
    assert resp.status_code == 200, f"Unexpected status {resp.status_code}"
    return time.perf_counter() - t0


async def _benchmark_app(
    app: XMLRPCASGIApp,
    *,
    n_requests: int,
    concurrency: int,
) -> list[float]:
    """Run n_requests with up to *concurrency* in flight and return latencies."""
    body = _build_request_body(1)
    latencies: list[float] = []

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://test",
    ) as client:
        sem = asyncio.Semaphore(concurrency)

        async def one_request() -> None:
            async with sem:
                latencies.append(await _run_single(client, body))

        tasks = [asyncio.create_task(one_request()) for _ in range(n_requests)]
        await asyncio.gather(*tasks)

    return latencies


def run_scenario(
    label: str,
    handler_fn: object,
    *,
    n_requests: int,
    concurrency: int,
    max_workers: int,
) -> None:
    """Build an app, run the benchmark, and print a summary line."""
    app = XMLRPCASGIApp(max_workers=max_workers)
    app.register_function(handler_fn, "inc")  # type: ignore[arg-type]

    t_wall = time.perf_counter()
    latencies = asyncio.run(_benchmark_app(app, n_requests=n_requests, concurrency=concurrency))
    elapsed = time.perf_counter() - t_wall

    app.close()

    rps = n_requests / elapsed
    p50 = statistics.median(latencies) * 1000
    p95 = sorted(latencies)[int(len(latencies) * 0.95)] * 1000
    p99 = sorted(latencies)[int(len(latencies) * 0.99)] * 1000

    print(
        f"  {label:<22s}  {rps:>8.1f} req/s  "
        f"p50={p50:>6.2f}ms  p95={p95:>6.2f}ms  p99={p99:>6.2f}ms  "
        f"wall={elapsed:.2f}s"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark XMLRPCASGIApp")
    parser.add_argument("--requests", type=int, default=500, help="Total requests per scenario")
    parser.add_argument("--concurrency", type=int, default=20, help="Max concurrent in-flight requests")
    parser.add_argument("--sleep", type=float, default=0.01, help="Handler sleep time in seconds")
    parser.add_argument("--workers", type=int, default=8, help="Thread-pool size for sync handlers")
    args = parser.parse_args()

    # Patch sleep time into the handlers via default-arg shadowing
    async def async_io(x: int) -> int:  # type: ignore[misc]
        await asyncio.sleep(args.sleep)
        return x + 1

    def sync_pool(x: int) -> int:  # type: ignore[misc]
        time.sleep(args.sleep)
        return x + 1

    print("=" * 76)
    print("XMLRPCASGIApp — in-process benchmark (httpx.ASGITransport, no TCP)")
    print(f"  requests={args.requests}  concurrency={args.concurrency}  sleep={args.sleep}s  workers={args.workers}")
    print("=" * 76)

    scenarios: list[tuple[str, object]] = [
        ("async  (asyncio.sleep)", async_io),
        ("sync   (time.sleep)", sync_pool),
        ("instant (no sleep)", instant_handler),
    ]

    for label, fn in scenarios:
        run_scenario(
            label,
            fn,
            n_requests=args.requests,
            concurrency=args.concurrency,
            max_workers=args.workers,
        )

    print("=" * 76)
    print("Notes:")
    print("  • 'async' handlers bypass the thread pool (event-loop native).")
    print("  • 'sync' handlers run in the thread pool via asyncio.to_thread.")
    print("  • 'instant' measures XML-RPC parse/marshal overhead only.")
    print("  • In-process transport removes TCP stack latency.")
    print("  • For network-stack comparison see benchmarks/benchmark_server.py.")


if __name__ == "__main__":
    main()
