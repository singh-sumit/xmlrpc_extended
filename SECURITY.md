# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅ Yes    |

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Report security issues privately by emailing **singhsumit9824@gmail.com** with the subject line:

```
[xmlrpc_extended] Security vulnerability report
```

Include:
- A description of the vulnerability and its potential impact.
- Steps to reproduce or a minimal proof-of-concept.
- The version(s) affected.

You can expect an acknowledgement within **72 hours** and a resolution timeline within **14 days** for confirmed issues.

---

## Security posture and safe-usage guide

### Trust boundary

`xmlrpc_extended` is built on Python's stdlib `xmlrpc.server`, which is designed for **trusted, private networks only**. It provides no built-in authentication, no TLS, and no input sanitisation beyond what is documented here.

**Do not expose an `xmlrpc_extended` server directly to the public internet.**

### Network exposure

| Deployment | Recommendation |
|------------|---------------|
| Internal microservice | Bind to `127.0.0.1` or a private network interface only |
| LAN service | Bind to a specific NIC; add network-layer access controls |
| Public-facing | Route through a reverse proxy with TLS, authentication, and rate-limiting |

### TLS termination

`xmlrpc_extended` does not handle TLS. If the endpoint must be reachable over an untrusted network, terminate TLS at a reverse proxy (nginx, Caddy, HAProxy) and forward plain HTTP to the server on `localhost`.

### Authentication

XML-RPC has no built-in authentication. Options:

- **Network isolation** — only allow trusted clients via firewall rules.
- **Reverse proxy auth** — handle Basic Auth or mutual TLS at the proxy layer.
- **Application-layer auth** — validate a shared secret passed as a method argument (acceptable for private services; not for public ones).

### `allow_dotted_names` — critical risk

Never call `register_instance(obj, allow_dotted_names=True)` unless you fully control every attribute of the registered object and every caller. `allow_dotted_names` enables callers to traverse arbitrary Python attribute chains, which can expose internal objects and methods unintentionally.

### Request size limits

Always configure `max_request_size` to match the largest legitimate payload your handlers accept:

```python
server = ThreadPoolXMLRPCServer(
    ("127.0.0.1", 8000),
    max_request_size=64 * 1024,  # 64 KiB — example
)
```

The default is **1 MiB**. Tune it down for services that only receive small payloads.

### Restricting accepted URL paths

By default the server accepts XML-RPC requests at `/` and `/RPC2`. Restrict this using `rpc_paths`:

```python
server = ThreadPoolXMLRPCServer(
    ("127.0.0.1", 8000),
    rpc_paths=("/rpc",),  # only /rpc is accepted; all others return 404
)
```

### Introspection

`register_introspection_functions()` exposes the list of all registered methods to any caller. Disable it in production if method enumeration is undesirable.

### Dependency and supply-chain hygiene

`xmlrpc_extended` has **zero runtime dependencies** beyond the Python standard library. Pin the package version in your project requirements to avoid unexpected updates:

```
xmlrpc_extended==0.1.0
```

Verify the distribution hash after download when operating in high-security environments.

### Checklist for production deployments

- [ ] Server bound to `127.0.0.1` or a private interface only
- [ ] `max_request_size` tuned to the smallest acceptable value
- [ ] `allow_dotted_names=False` (this is the default — do not override)
- [ ] Introspection disabled or access-controlled
- [ ] `rpc_paths` restricted to the minimum required set
- [ ] TLS terminated at a reverse proxy
- [ ] Authentication enforced at the network or proxy layer
- [ ] Package version pinned in requirements

