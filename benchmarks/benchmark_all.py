"""Unified benchmark: all XML-RPC implementations compared side by side.

Covers four server implementations across two workload profiles:

  fast  – handler returns immediately (measures framework overhead)
  slow  – handler sleeps to simulate I/O-bound work

Implementations
---------------
TCP-based (real loopback network stack, xmlrpc.client callers):

  SimpleXMLRPCServer      stdlib, single-threaded (one request at a time)
  ThreadedXMLRPCServer    stdlib + ThreadingMixIn, one OS thread per request
  ThreadPoolXMLRPCServer  xmlrpc_extended, bounded ThreadPoolExecutor

ASGI in-process (httpx.ASGITransport, no TCP/kernel overhead):

  XMLRPCASGIApp [async]   async def handler, runs natively in the event loop
  XMLRPCASGIApp [sync]    sync handler, delegated to thread pool via asyncio.to_thread

The two sections have different transport overheads:
  * TCP numbers include loopback socket + HTTP framing + xmlrpc.client marshalling.
  * ASGI numbers exclude the TCP stack; only XML-RPC parse/dispatch/marshal
    and handler execution are measured.
To benchmark XMLRPCASGIApp over real TCP, run it under an ASGI server::

    uvicorn --workers 1 --host 127.0.0.1 --port 8000 <module>:app

Usage::

    python benchmarks/benchmark_all.py [--requests N] [--clients N] [--sleep S]

Requirements::

    pip install httpx anyio        # already in [dev] extras
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import threading
import time
import xmlrpc.client
import xmlrpc.server
from collections.abc import Callable, Generator
from contextlib import contextmanager
from socketserver import ThreadingMixIn

import httpx

from xmlrpc_extended import ServerOverloadPolicy, ThreadPoolXMLRPCServer
from xmlrpc_extended.asgi import XMLRPCASGIApp

# ---------------------------------------------------------------------------
# Shared handler functions
# ---------------------------------------------------------------------------


def fast_handler(x: int) -> int:
    """Return immediately — measures pure framework overhead."""
    return x + 1


def slow_handler(x: int, sleep: float = 0.02) -> int:
    """Sleep to simulate I/O-bound work (DB query, HTTP call, file I/O)."""
    time.sleep(sleep)
    return x + 1


# ---------------------------------------------------------------------------
# Server context managers — TCP based
# ---------------------------------------------------------------------------


@contextmanager
def _simple_server() -> Generator[str, None, None]:
    """stdlib SimpleXMLRPCServer — single-threaded, one request at a time."""
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


class _ThreadedXMLRPCServer(ThreadingMixIn, xmlrpc.server.SimpleXMLRPCServer):
    """stdlib SimpleXMLRPCServer with ThreadingMixIn — one OS thread per request."""

    daemon_threads = True


@contextmanager
def _threaded_server() -> Generator[str, None, None]:
    """stdlib + ThreadingMixIn — unbounded, one OS thread spawned per request."""
    server = _ThreadedXMLRPCServer(
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
    """xmlrpc_extended ThreadPoolXMLRPCServer — bounded thread pool."""
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
# TCP benchmark runner
# ---------------------------------------------------------------------------


def run_tcp_scenario(
    url: str,
    *,
    method: str,
    num_clients: int,
    num_requests: int,
    sleep: float,
) -> dict[str, float]:
    """Send *num_requests* from *num_clients* threads; return timing stats."""
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
        "rps": round(n / wall, 1) if wall > 0 else 0.0,
        "mean_ms": round(statistics.mean(latencies) * 1000, 2) if latencies else 0.0,
        "p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95)] * 1000, 2) if latencies else 0.0,
        "p99_ms": round(sorted(latencies)[int(len(latencies) * 0.99)] * 1000, 2) if latencies else 0.0,
    }


# ---------------------------------------------------------------------------
# ASGI in-process runner
# ---------------------------------------------------------------------------


# ASGI requests always call a single-arg method "rpc" — sleep is baked into the handler closure.
_ASGI_REQUEST_BODY = xmlrpc.client.dumps((1,), "rpc").encode()


async def _run_asgi_scenario(
    app: XMLRPCASGIApp,
    *,
    n_requests: int,
    concurrency: int,
) -> list[float]:
    body = _ASGI_REQUEST_BODY
    latencies: list[float] = []

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://test",
    ) as client:
        sem = asyncio.Semaphore(concurrency)

        async def one() -> None:
            async with sem:
                t0 = time.perf_counter()
                resp = await client.post("/", content=body, headers={"Content-Type": "text/xml"})
                assert resp.status_code == 200
                latencies.append(time.perf_counter() - t0)

        await asyncio.gather(*[asyncio.create_task(one()) for _ in range(n_requests)])

    return latencies


def run_asgi_scenario(
    handler_fn: Callable[..., object],
    *,
    n_requests: int,
    concurrency: int,
    max_workers: int,
) -> dict[str, float]:
    """Run ASGI in-process benchmark; return timing stats."""
    app = XMLRPCASGIApp(max_workers=max_workers)
    app.register_function(handler_fn, "rpc")  # sleep is baked into handler closures

    wall_start = time.perf_counter()
    latencies = asyncio.run(_run_asgi_scenario(app, n_requests=n_requests, concurrency=concurrency))
    wall = time.perf_counter() - wall_start
    app.close()

    n = len(latencies)
    return {
        "requests_sent": n,
        "errors": 0,
        "wall_s": round(wall, 3),
        "rps": round(n / wall, 1) if wall > 0 else 0.0,
        "mean_ms": round(statistics.mean(latencies) * 1000, 2) if latencies else 0.0,
        "p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95)] * 1000, 2) if latencies else 0.0,
        "p99_ms": round(sorted(latencies)[int(len(latencies) * 0.99)] * 1000, 2) if latencies else 0.0,
    }


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

COL_W = 42


def print_header(title: str, width: int = 100) -> None:
    print("=" * width)
    print(f"  {title}")
    print("=" * width)
    print(f"  {'Implementation':<{COL_W}} {'RPS':>8}  {'mean':>8}  {'p95':>8}  {'p99':>8}  {'errors':>6}")
    print(f"  {'-' * COL_W} {'-' * 8}  {'-' * 8}  {'-' * 8}  {'-' * 8}  {'-' * 6}")


def print_row(label: str, stats: dict[str, float]) -> None:
    print(
        f"  {label:<{COL_W}} "
        f"{stats['rps']:>8.1f}  "
        f"{stats['mean_ms']:>7.2f}ms  "
        f"{stats['p95_ms']:>7.2f}ms  "
        f"{stats['p99_ms']:>7.2f}ms  "
        f"{int(stats['errors']):>6}"
    )


def print_separator() -> None:
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="xmlrpc_extended unified benchmark")
    parser.add_argument("--requests", type=int, default=200, help="Total requests per scenario (default: 200)")
    parser.add_argument("--clients", type=int, default=8, help="Concurrent TCP clients / ASGI concurrency (default: 8)")
    parser.add_argument("--sleep", type=float, default=0.02, help="Slow handler sleep in seconds (default: 0.02)")
    parser.add_argument("--workers", type=int, default=8, help="Thread-pool size for pool/ASGI-sync (default: 8)")
    args = parser.parse_args()

    print()
    print(
        f"  requests={args.requests}  clients/concurrency={args.clients}  sleep={args.sleep}s  workers={args.workers}"
    )

    # ------------------------------------------------------------------
    # Section A: TCP-based servers
    # ------------------------------------------------------------------

    print_header(
        "Section A — TCP-based servers (loopback socket + xmlrpc.client)",
        width=100,
    )

    with (
        _simple_server() as simple_url,
        _threaded_server() as threaded_url,
        _pool_server(max_workers=args.workers) as pool_url,
    ):
        for scenario, method in [("fast [no sleep]", "fast"), ("slow [I/O sim]", "slow")]:
            for label, url in [
                (f"SimpleXMLRPCServer          {scenario}", simple_url),
                (f"ThreadedXMLRPCServer        {scenario}", threaded_url),
                (f"ThreadPoolXMLRPCServer      {scenario}", pool_url),
            ]:
                stats = run_tcp_scenario(
                    url,
                    method=method,
                    num_clients=args.clients,
                    num_requests=args.requests,
                    sleep=args.sleep,
                )
                print_row(label, stats)
            print_separator()

    # ------------------------------------------------------------------
    # Section B: ASGI in-process
    # ------------------------------------------------------------------

    print_header(
        "Section B — XMLRPCASGIApp in-process (httpx.ASGITransport, no TCP overhead)",
        width=100,
    )
    print(f"  {'Note: excludes TCP/kernel stack; numbers will be higher than real-network ASGI.'}")
    print()

    async def async_slow(x: int) -> int:  # sleep baked in — no extra XML-RPC arg needed
        await asyncio.sleep(args.sleep)
        return x + 1

    def sync_slow(x: int) -> int:  # sleep baked in
        time.sleep(args.sleep)
        return x + 1

    async def async_fast(x: int) -> int:
        return x + 1

    for label, handler_fn in [
        ("XMLRPCASGIApp [async slow — asyncio.sleep]", async_slow),
        ("XMLRPCASGIApp [sync  slow — time.sleep   ]", sync_slow),
        ("XMLRPCASGIApp [async fast — no sleep      ]", async_fast),
    ]:
        stats = run_asgi_scenario(
            handler_fn,
            n_requests=args.requests,
            concurrency=args.clients,
            max_workers=args.workers,
        )
        print_row(label, stats)

    print()
    print("=" * 100)
    print("Notes:")
    print("  • Section A uses real loopback TCP sockets → numbers include OS + HTTP framing overhead.")
    print("  • Section B uses in-process transport → no OS scheduler, no TCP — measures handler + XML-RPC overhead.")
    print("  • ThreadedXMLRPCServer spawns one OS thread per request; fine for low load, risky under burst.")
    print("  • ThreadPoolXMLRPCServer bounds parallelism; use BLOCK/FAULT/HTTP_503 when all slots are full.")
    print("  • XMLRPCASGIApp async handlers bypass the thread pool — prefer for I/O-bound work.")
    print("  • XMLRPCASGIApp sync handlers run via asyncio.to_thread — tune max_workers to concurrency.")
    print("=" * 100)


if __name__ == "__main__":
    main()
