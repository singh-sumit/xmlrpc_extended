# ASGI Integration

`xmlrpc_extended.asgi` provides **`XMLRPCASGIApp`** — a zero-dependency,
ASGI 3-compliant XML-RPC application that runs on any ASGI server
(uvicorn, hypercorn, granian, daphne, …).

---

## Why ASGI?

| Feature | `ThreadPoolXMLRPCServer` | `XMLRPCASGIApp` |
|---------|--------------------------|-----------------|
| Transport | TCP (built-in `http.server`) | Any ASGI server |
| Async handlers | ✗ | ✓ (awaited directly) |
| Sync handlers | ✓ (in thread pool) | ✓ (in thread pool) |
| I/O multiplexing | ✗ | ✓ (single event loop) |
| TLS termination | External reverse proxy | ASGI server handles it |
| HTTP/2 | ✗ | ✓ (depends on ASGI server) |
| Graceful reload | ✗ | ✓ (ASGI lifespan) |
| Runtime deps | None | None |

**Choose `XMLRPCASGIApp` when you**:

- Want to add XML-RPC to an existing **ASGI application** (FastAPI, Starlette, etc.)
- Have I/O-bound handlers that benefit from `async def`
- Need TLS, HTTP/2, or graceful hot-reload via an existing ASGI server
- Are deploying with uvicorn / hypercorn / granian

**Choose `ThreadPoolXMLRPCServer` when you**:

- Want the simplest possible standalone server with no ASGI dependency
- Need compatibility with older Python toolchains

---

## Quick start

```python
# app.py
from xmlrpc_extended.asgi import XMLRPCASGIApp

app = XMLRPCASGIApp(rpc_path="/rpc", max_workers=4)

# Sync handler — automatically runs in the thread pool
def add(a: int, b: int) -> int:
    return a + b

# Async handler — awaited directly in the event loop
async def lookup(key: str) -> dict:
    # await some_db_call(key)
    return {"key": key, "value": 42}

app.register_function(add, "add")
app.register_function(lookup, "lookup")
```

Run with any ASGI server:

```console
# uvicorn
uvicorn app:app --host 0.0.0.0 --port 8000

# hypercorn
hypercorn app:app --bind 0.0.0.0:8000

# granian
granian --interface asgi app:app
```

Call from a client:

```python
import xmlrpc.client

with xmlrpc.client.ServerProxy("http://localhost:8000/rpc") as proxy:
    print(proxy.add(1, 2))       # → 3
    print(proxy.lookup("name"))  # → {'key': 'name', 'value': 42}
```

---

## Constructor reference

```python
XMLRPCASGIApp(
    *,
    max_workers: int = 4,
    max_request_size: int = 1_048_576,   # 1 MiB
    rpc_path: str = "/",
    allow_none: bool = False,
    encoding: str | None = None,
    use_builtin_types: bool = False,
)
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_workers` | `4` | Thread-pool size for sync handlers. `async def` handlers bypass this pool. |
| `max_request_size` | `1 048 576` (1 MiB) | Maximum body size in bytes. Larger requests get `413 Payload Too Large`. |
| `rpc_path` | `"/"` | URL path that accepts XML-RPC `POST` requests. All other paths return `404`. |
| `allow_none` | `False` | Allow `None` in XML-RPC payloads (non-standard extension). |
| `encoding` | UTF-8 | XML encoding override. |
| `use_builtin_types` | `False` | Map `dateTime` / `base64` to Python `datetime` / `bytes`. |

---

## Registering methods

`XMLRPCASGIApp` inherits from
[`SimpleXMLRPCDispatcher`](https://docs.python.org/3/library/xmlrpc.server.html#xmlrpc.server.SimpleXMLRPCDispatcher)
and supports the full registration API:

```python
app = XMLRPCASGIApp()

# Register a named function (sync or async)
app.register_function(my_func, "my_func")

# Register all public methods of an instance
app.register_instance(MyService())

# Enable system.listMethods / system.methodHelp / system.methodSignature
app.register_introspection_functions()

# Enable system.multicall
app.register_multicall_functions()
```

### Mixing sync and async handlers

```python
import asyncio
import time

async def fast_io_bound(x: int) -> int:
    """Async — runs in the event loop; best for async I/O."""
    await asyncio.sleep(0)  # simulates async DB query
    return x * 2

def legacy_blocking(x: int) -> int:
    """Sync — runs in thread pool; best for legacy blocking code."""
    time.sleep(0.001)
    return x + 1

app = XMLRPCASGIApp(max_workers=8)
app.register_function(fast_io_bound, "fast_io_bound")
app.register_function(legacy_blocking, "legacy_blocking")
```

---

## ASGI lifespan

`XMLRPCASGIApp` implements the **ASGI lifespan protocol** (startup/shutdown):

- **startup** — creates the `ThreadPoolExecutor` for sync handlers
- **shutdown** — waits for all in-flight sync handlers to complete, then closes the pool

Most ASGI servers send lifespan events automatically.  When running without a
lifespan-aware server (e.g. in tests), the executor is created lazily on the
first request and you must call `app.close()` to release resources:

```python
app = XMLRPCASGIApp()
app.register_function(lambda x: x + 1, "inc")

# ... use app in tests ...

app.close()  # release the thread pool
```

---

## HTTP semantics

| Method | Path | Body | Response |
|--------|------|------|----------|
| `POST` | `rpc_path` | XML-RPC payload | `200 OK` + XML-RPC response |
| `POST` | other path | any | `404 Not Found` |
| `GET`, `PUT`, … | any | any | `405 Method Not Allowed` (with `Allow: POST`) |
| `POST` | `rpc_path` | body > `max_request_size` | `413 Payload Too Large` |
| `POST` | `rpc_path` | malformed XML | `200 OK` + XML-RPC fault (`-32700`) |

---

## Deployment recipes

### With uvicorn (production)

```console
pip install uvicorn[standard]
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 1
```

!!! note
    Use `--workers 1` for async apps — async I/O multiplexes multiple
    clients on a single process.  For CPU-bound workloads, use
    `xmlrpc_extended.multiprocess.spawn_workers` with SO_REUSEPORT instead.

### With hypercorn (HTTP/2, TLS)

```console
pip install hypercorn
hypercorn --bind 0.0.0.0:8443 --certfile cert.pem --keyfile key.pem app:app
```

### Behind a reverse proxy

```nginx
location /rpc {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
}
```

### Mounting in a Starlette / FastAPI app

```python
from fastapi import FastAPI
from starlette.routing import Mount
from xmlrpc_extended.asgi import XMLRPCASGIApp

rpc = XMLRPCASGIApp(rpc_path="/rpc")
rpc.register_function(lambda a, b: a + b, "add")

web = FastAPI()

# Mount the XML-RPC app at /rpc
web.mount("/rpc", rpc)
```

---

## Testing

Test `XMLRPCASGIApp` in-process with `httpx.ASGITransport` — no real server
needed:

```python
import asyncio
import xmlrpc.client
import httpx
from xmlrpc_extended.asgi import XMLRPCASGIApp

app = XMLRPCASGIApp()
app.register_function(lambda a, b: a + b, "add")

async def test():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        body = xmlrpc.client.dumps((1, 2), "add").encode()
        response = await client.post("/", content=body, headers={"Content-Type": "text/xml"})

    result, _ = xmlrpc.client.loads(response.content)
    assert result[0] == 3

asyncio.run(test())
app.close()
```

---

## Migration from `ThreadPoolXMLRPCServer`

| `ThreadPoolXMLRPCServer` | `XMLRPCASGIApp` |
|--------------------------|-----------------|
| `server = ThreadPoolXMLRPCServer(("0.0.0.0", 8000))` | `app = XMLRPCASGIApp()` |
| `server.register_function(fn, "name")` | `app.register_function(fn, "name")` ← identical |
| `server.register_instance(obj)` | `app.register_instance(obj)` ← identical |
| `server.serve_forever()` | `uvicorn app:app` |
| `max_workers=N` | `max_workers=N` ← identical |
| `max_request_size=N` | `max_request_size=N` ← identical |
| No async support | `async def` handlers supported natively |

The method-registration API is **100% compatible** — the same
`register_function` / `register_instance` calls work unchanged.

---

!!! warning "Security note"
    Do **not** enable `allow_dotted_names=True` when registering an instance.
    It bypasses the security checks that prevent callers from traversing
    arbitrary object attributes as callable RPC methods.

!!! tip "Performance tip"
    For CPU-bound sync handlers, increase `max_workers` to match concurrency:
    a good starting point is `max_workers = expected_concurrency`.

    For async I/O-bound handlers, the thread pool is never used — set
    `max_workers=1` to save resources.
