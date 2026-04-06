# xmlrpc_extended — AI Agent Instructions

> This file gives AI coding assistants (Claude, GPT-4o, Gemini, etc.) the
> project context needed to contribute effectively.  Read it before writing
> any code, tests, or documentation changes.

---

## Project overview

`xmlrpc_extended` is a **pure-stdlib Python package** (no runtime dependencies)
that extends `SimpleXMLRPCServer` with:

- Bounded `ThreadPoolExecutor`-based concurrency
- Explicit overload policies (BLOCK / CLOSE / FAULT / HTTP_503)
- Real-time stats via `server.stats()` → `ServerStats` frozen dataclass
- Configurable URL path restriction via `rpc_paths`
- Optional client helper: `XMLRPCClient` context manager with timeout
- Linux-only scale-out via `SO_REUSEPORT` (`xmlrpc_extended.multiprocess`)

**Minimum Python version:** 3.10  
**Target audience:** Python developers running internal RPC services or
embedded servers.

---

## Repository layout

```
src/xmlrpc_extended/
    __init__.py          # Public re-exports only
    server.py            # Core: ThreadPoolXMLRPCServer, overload policies,
                         #       ServerStats, LimitedXMLRPCRequestHandler
    client.py            # Optional: XMLRPCClient context manager
    multiprocess.py      # Optional: SO_REUSEPORT helpers (Linux only)

tests/
    test_server.py       # Unit tests for server.py (45 tests, 1 skipped)
    test_extras.py       # Unit tests for client.py and multiprocess.py

benchmarks/
    benchmark_server.py  # SimpleXMLRPCServer vs ThreadPoolXMLRPCServer perf

docs/                    # MkDocs Material site source
mkdocs.yml               # Docs site config
.pre-commit-config.yaml  # Pre-commit hooks (ruff + mypy + hygiene)
pyproject.toml           # Build config, tool config (ruff, mypy)
```

---

## Development workflow

### 1. Environment setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

### 2. TDD — always write tests first

This project follows **strict TDD**:

1. Write a failing test in `tests/test_server.py` or `tests/test_extras.py`
2. Run `python -m unittest discover -s tests -v` — confirm it fails
3. Implement the minimum code to make it pass
4. Refactor while keeping all tests green

Every public behaviour change **must** include a test. PRs without tests for
new behaviour will not be merged.

### 3. Lint and type check before committing

```bash
ruff check --fix src tests   # lint (auto-fixes safe issues)
ruff format src tests        # formatter
mypy src                     # strict type checking
```

Or just run pre-commit which does all three:

```bash
pre-commit run --all-files
```

### 4. Run the test suite

```bash
python -m unittest discover -s tests -v
# Expected: 45 tests, 1 skipped (SO_REUSEPORT skips on non-Linux)
```

---

## Code conventions

### Style

- **Line length:** 120 characters (`[tool.ruff] line-length = 120`)
- **Formatter:** `ruff format` (replaces black)
- **Imports:** `ruff` enforces `isort` ordering (E, F, W, I, UP rules)
- **Type annotations:** required on all public functions and methods; mypy
  `strict = true` must pass
- **Docstrings:** Google style (`Args:`, `Returns:`, `Raises:`, `Example:`)

### Naming

| Thing | Convention |
|-------|-----------|
| Classes | `UpperCamelCase` |
| Functions/methods | `snake_case` |
| Private members | `_leading_underscore` |
| Constants | `UPPER_SNAKE_CASE` |
| Type aliases | `UpperCamelCase` |

### Patterns to follow

- `from __future__ import annotations` at the top of every source file
- Use `dataclasses.dataclass(frozen=True)` for value objects
- Use `threading.Lock` (not `RLock`) unless re-entry is genuinely needed
- Use `typing.Any` sparingly — prefer `object` for truly unknown types
- Use `collections.abc.Callable` instead of `typing.Callable` (UP035)
- Prefer `contextlib.suppress` over bare `except: pass`

### Patterns to avoid

- **No bare `except:`** — always catch specific exceptions
- **No mutable default arguments** — use `None` and initialise inside the body
- **No `threading.Thread` subclassing** — use `ThreadPoolExecutor` callbacks
- **No global mutable state** — all state lives on the server instance
- **No monkey-patching** — tests use real servers on random ports
- **No `time.sleep` in production code** — only in tests and benchmarks

---

## Public API surface

The following names are stable public API (exported from `__init__.py`):

```python
from xmlrpc_extended import (
    LimitedXMLRPCRequestHandler,  # request handler with body size limit
    ServerOverloadPolicy,          # Enum: BLOCK, CLOSE, FAULT, HTTP_503
    ServerStats,                   # frozen dataclass: activity counters snapshot
    ThreadPoolXMLRPCServer,        # the main server class
    XMLRPCServerConfig,            # frozen dataclass: constructor parameters
)
from xmlrpc_extended.client import XMLRPCClient       # timeout-aware client CM
from xmlrpc_extended.multiprocess import (             # Linux SO_REUSEPORT helpers
    create_reuseport_socket,
    spawn_workers,
)
```

**Invariants to preserve:**

1. `ThreadPoolXMLRPCServer` must be a drop-in replacement for
   `SimpleXMLRPCServer` — no existing constructor parameters may be removed or
   have their semantics changed.
2. `server.stats()` must be thread-safe and non-blocking.
3. `ServerStats` must remain a frozen dataclass (immutable snapshot).
4. `ServerOverloadPolicy` strings must remain lowercase (config-file friendly).
5. `SO_REUSEPORT` helpers must raise `OSError` gracefully on non-Linux,  not
   `AttributeError` or `ImportError`.

---

## XML-RPC domain knowledge

- XML-RPC transports all data as XML over HTTP POST
- Fault responses use HTTP 200 with an `<fault>` element — this is spec-correct
- `xmlrpc.client.ServerProxy.__getattr__` intercepts attribute access and
  converts it to an RPC call — avoid calling dunder methods on a proxy object
- `SimpleXMLRPCRequestHandler` inherits from `BaseHTTPRequestHandler`; the
  `do_POST` method parses the request and dispatches to registered methods
- The `allow_dotted_names` constructor parameter is unsafe — it can expose
  internal attributes; never enable it in production code

---

## Testing patterns

### Server-under-test pattern

Every test class follows this pattern:

```python
class MyFeatureTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadPoolXMLRPCServer(
            ("127.0.0.1", 0),   # port 0 = OS assigns free port
            max_workers=2,
            logRequests=False,
        )
        self.server.register_function(lambda: None, "ping")
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
```

### Making an XML-RPC call

```python
import xmlrpc.client

proxy = xmlrpc.client.ServerProxy(f"http://127.0.0.1:{self.port}/")
result = proxy.ping()
proxy.__close_connection_to_server__()  # but use type()-based close; see client.py
```

### Timing-sensitive assertions

When asserting on async side-effects (e.g. stats counters after a call
returns), add a short sleep:

```python
import time
proxy.ping()
time.sleep(0.05)  # allow worker thread to increment counter
snap = self.server.stats()
self.assertGreaterEqual(snap.completed, 1)
```

---

## Adding a new overload policy

1. Add the enum value to `ServerOverloadPolicy` in `server.py`
2. Add a `record_rejected_…` method to `_StatsTracker`
3. Add the corresponding field to `ServerStats`
4. Handle the new policy in `_reject_request()`
5. Add tests in `ServerStatsTests` and a dedicated policy test class
6. Update the overload policy table in `docs/user-guide/overload-policies.md`

---

## CI checks

Every PR must pass:

| Check | Command |
|-------|---------|
| Ruff lint | `ruff check src tests` |
| Mypy | `mypy src` |
| Tests (4 Python versions) | `python -m unittest discover -s tests -v` |
| Docs build | `mkdocs build --strict` |

---

## Questions and discussion

Open a [GitHub Discussion](https://github.com/singh-sumit/xmlrpc_extended/discussions) — do not email the maintainer.
