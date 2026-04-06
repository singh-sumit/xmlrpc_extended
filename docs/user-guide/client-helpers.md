# Client Helpers

The optional `xmlrpc_extended.client` module provides `XMLRPCClient`, a
context-manager wrapper around `xmlrpc.client.ServerProxy` that:

- enforces an explicit **connection timeout** so hung servers do not block
  callers indefinitely (the stdlib default is no timeout)
- guarantees the underlying connection is **closed on exit**, even if an
  exception is raised inside the `with` block

---

## Basic usage

```python
from xmlrpc_extended.client import XMLRPCClient

with XMLRPCClient("http://127.0.0.1:8000/", timeout=5.0) as proxy:
    result = proxy.add(1, 2)   # raises socket.timeout if server is silent > 5 s
    print(result)              # → 3
```

---

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `uri` | `str` | — | Full URL of the XML-RPC endpoint |
| `timeout` | `float` | `30.0` | Socket timeout in seconds |
| `allow_none` | `bool` | `False` | Permit `None` values in payloads |
| `use_builtin_types` | `bool` | `False` | Map XML-RPC `dateTime`/`base64` to Python built-ins |

---

## Handling errors

```python
import xmlrpc.client
import socket

with XMLRPCClient("http://127.0.0.1:8000/", timeout=2.0) as proxy:
    try:
        result = proxy.slow_method()
    except xmlrpc.client.Fault as exc:
        # Overload policy FAULT or application error
        print(f"XML-RPC fault {exc.faultCode}: {exc.faultString}")
    except (ConnectionError, TimeoutError, socket.timeout):
        # Network or timeout error
        print("Could not reach server")
```

---

## Retry pattern

XML-RPC methods are **not necessarily idempotent**, so `XMLRPCClient` does not
retry automatically. Wrap in a retry loop when it is safe to do so:

```python
import time
import xmlrpc.client
from xmlrpc_extended.client import XMLRPCClient

def call_with_retry(uri: str, method: str, *args, retries: int = 3, backoff: float = 0.5):
    for attempt in range(retries):
        try:
            with XMLRPCClient(uri, timeout=5.0) as proxy:
                return getattr(proxy, method)(*args)
        except (xmlrpc.client.Fault, ConnectionError):
            if attempt == retries - 1:
                raise
            time.sleep(backoff * (2 ** attempt))
```

---

## Why not just use `ServerProxy` directly?

`xmlrpc.client.ServerProxy` does not set a socket timeout by default, meaning a
hung server will block the caller forever. `XMLRPCClient` injects a
`_TimeoutTransport` that sets `connection.timeout` on every new socket, giving
you fine-grained control from day one.
