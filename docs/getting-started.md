# Getting Started

## Requirements

- Python **3.10** or later
- No runtime dependencies — only the standard library

## Installation

=== "pip"

    ```console
    pip install xmlrpc-extended
    ```

=== "uv"

    ```console
    uv add xmlrpc-extended
    ```

=== "from source"

    ```console
    git clone https://github.com/singh-sumit/xmlrpc_extended.git
    cd xmlrpc_extended
    pip install -e ".[dev]"
    ```

---

## Your first server

Create `server.py`:

```python title="server.py"
from xmlrpc_extended import ServerOverloadPolicy, ThreadPoolXMLRPCServer


def add(left: int, right: int) -> int:
    return left + right


def multiply(left: int, right: int) -> int:
    return left * right


if __name__ == "__main__":
    with ThreadPoolXMLRPCServer(
        ("127.0.0.1", 8000),
        max_workers=4,       # (1)!
        max_pending=8,       # (2)!
        overload_policy=ServerOverloadPolicy.FAULT,  # (3)!
        logRequests=False,
    ) as server:
        server.register_introspection_functions()
        server.register_function(add, "add")
        server.register_function(multiply, "multiply")
        print("Serving on http://127.0.0.1:8000/")
        server.serve_forever()
```

1. Up to 4 requests execute concurrently.
2. Up to 8 more may wait for a free worker slot.
3. Once all 12 slots are full, return an XML-RPC fault to the caller.

Run it:

```console
python server.py
```

Then call it from `client.py`:

```python title="client.py"
from xmlrpc_extended.client import XMLRPCClient

with XMLRPCClient("http://127.0.0.1:8000/", timeout=5.0) as proxy:
    print(proxy.add(1, 2))       # → 3
    print(proxy.multiply(6, 7))  # → 42
```

---

## Configuration quick-reference

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_workers` | `int` | `8` | Maximum concurrent worker threads |
| `max_pending` | `int \| None` | `None` = `max_workers` | Maximum queued requests beyond the active pool |
| `overload_policy` | `ServerOverloadPolicy` | `BLOCK` | What to do when capacity is exhausted |
| `max_request_size` | `int` | `1 048 576` (1 MiB) | Maximum accepted body size in bytes |
| `request_queue_size` | `int` | `64` | OS-level TCP accept backlog |
| `rpc_paths` | `tuple[str, ...] \| None` | `None` | Restrict accepted URL paths; `None` uses stdlib defaults (`/`, `/RPC2`) |
| `overload_fault_code` | `int` | `-32500` | XML-RPC fault code used by the `FAULT` policy |
| `overload_fault_string` | `str` | `"Server overloaded"` | XML-RPC fault string used by the `FAULT` policy |
| `logRequests` | `bool` | `True` | Enable/disable access logging |
| `allow_none` | `bool` | `False` | Allow `None` in XML-RPC payloads |

---

## Running the test suite

```console
python -m unittest discover -s tests -v
```

Expected: **45 tests pass, 1 skipped** (the `SO_REUSEPORT` test skips on non-Linux).

---

## Setting up for development

```console
# 1. Clone and create a virtual environment
git clone https://github.com/singh-sumit/xmlrpc_extended.git
cd xmlrpc_extended
python -m venv .venv && source .venv/bin/activate

# 2. Install dev dependencies
pip install -e ".[dev]"

# 3. Install pre-commit hooks (runs ruff + mypy on every commit)
pre-commit install

# 4. Verify everything is clean
pre-commit run --all-files
python -m unittest discover -s tests -v
```

---

## Serving the documentation locally

```console
pip install -e ".[docs]"
mkdocs serve
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).
