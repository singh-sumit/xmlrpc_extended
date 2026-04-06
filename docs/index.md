# xmlrpc_extended

**Thread-pool powered extensions for Python's built-in XML-RPC server.**

[![CI](https://github.com/singh-sumit/xmlrpc_extended/actions/workflows/ci.yml/badge.svg)](https://github.com/singh-sumit/xmlrpc_extended/actions/workflows/ci.yml)
[![Docs](https://github.com/singh-sumit/xmlrpc_extended/actions/workflows/docs.yml/badge.svg)](https://singh-sumit.github.io/xmlrpc_extended/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/singh-sumit/xmlrpc_extended/blob/main/LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

---

`xmlrpc_extended` upgrades Python's stdlib `SimpleXMLRPCServer` with:

- **Bounded thread pool** — serve requests concurrently instead of one-at-a-time
- **Overload protection** — block, drop, fault, or return HTTP 503 when saturated
- **Real-time metrics** — `server.stats()` gives a point-in-time counters snapshot
- **Path restriction** — accept XML-RPC only on specific URL paths
- **Client helpers** — `XMLRPCClient` context manager with configurable timeout
- **Linux scale-out** — `SO_REUSEPORT` multi-process workers via `xmlrpc_extended.multiprocess`
- **Zero dependencies** — pure stdlib; no pip-install surprise transitive deps

---

## Install

```console
pip install xmlrpc-extended
```

Requires Python 3.10+.

---

## 30-second quickstart

```python
from xmlrpc_extended import ServerOverloadPolicy, ThreadPoolXMLRPCServer


def add(left: int, right: int) -> int:
    return left + right


with ThreadPoolXMLRPCServer(
    ("127.0.0.1", 8000),
    max_workers=8,       # 8 concurrent requests
    max_pending=16,      # 16 more may queue
    overload_policy=ServerOverloadPolicy.HTTP_503,
    logRequests=False,
) as server:
    server.register_function(add, "add")
    server.serve_forever()
```

Callers use the standard `xmlrpc.client` or the bundled `XMLRPCClient` helper:

```python
from xmlrpc_extended.client import XMLRPCClient

with XMLRPCClient("http://127.0.0.1:8000/", timeout=5.0) as proxy:
    print(proxy.add(1, 2))  # → 3
```

---

## Quick navigation

<div class="grid cards" markdown>

- :material-rocket-launch: **[Getting Started](getting-started.md)**

    Install, configure, and run your first server in minutes.

- :material-book-open-variant: **[User Guide](user-guide/overload-policies.md)**

    Deep dives into overload policies, path restriction, metrics, client helpers, and scale-out.

- :material-code-braces: **[API Reference](api-reference/server.md)**

    Full auto-generated documentation for every public class and function.

- :material-sitemap: **[Architecture](architecture.md)**

    Request lifecycle, threading model, and class hierarchy as Mermaid diagrams.

- :material-chart-bar: **[Benchmarks](benchmarks.md)**

    Real numbers: `ThreadPoolXMLRPCServer` vs `SimpleXMLRPCServer` across different workload profiles.

- :material-shield-lock: **[Security](security.md)**

    Supported versions, vulnerability reporting, and the safe-usage guide.

</div>

---

## Why not just use `ThreadingMixIn`?

Python's stdlib ships `ThreadingMixIn` which spawns an *unbounded* thread per
request. Under load this creates thousands of threads and exhausts file
descriptors. `ThreadPoolXMLRPCServer` uses a **`ThreadPoolExecutor`** (bounded
workers) and an explicit **semaphore** to limit the total outstanding
requests — giving you predictable memory footprint and explicit overload
behaviour.

---

## Community

Questions, ideas, and discussion → [GitHub Discussions](https://github.com/singh-sumit/xmlrpc_extended/discussions)

Bugs and feature requests → [GitHub Issues](https://github.com/singh-sumit/xmlrpc_extended/issues)
