# Path Restriction (`rpc_paths`)

By default `ThreadPoolXMLRPCServer` inherits stdlib behaviour and accepts
XML-RPC `POST` requests on **`/`** and **`/RPC2`**. Any other path returns
`404 Not Found`.

---

## Restricting to a single path

Pass a tuple of allowed paths via the `rpc_paths` parameter:

```python
server = ThreadPoolXMLRPCServer(
    ("127.0.0.1", 8000),
    rpc_paths=("/rpc",),  # only /rpc is accepted
)
```

A request to `/` or `/RPC2` now returns **404**.

---

## Multiple allowed paths

```python
server = ThreadPoolXMLRPCServer(
    ("127.0.0.1", 8000),
    rpc_paths=("/rpc", "/api/v1/rpc"),
)
```

---

## Restoring stdlib defaults

Pass `rpc_paths=None` (the default) to restore the stdlib `("/", "/RPC2")`
behaviour, or pass the tuple explicitly:

```python
server = ThreadPoolXMLRPCServer(
    ("127.0.0.1", 8000),
    rpc_paths=("/", "/RPC2"),  # explicit stdlib defaults
)
```

---

## Why restrict paths?

- Reduces the attack surface: scanners probing common paths get 404 instead of
  a valid XML-RPC response.
- Allows placing other HTTP handlers at different paths in a reverse-proxy
  config (e.g. `/health` handled by the proxy, `/rpc` forwarded to the server).
- Makes path-based routing in a service mesh predictable.

!!! tip
    Combine `rpc_paths` with the `HTTP_503` overload policy and a reverse proxy
    that health-checks `/` — the proxy gets 404 for `/` (not a live path) and
    separately sends XML-RPC traffic to `/rpc`.
