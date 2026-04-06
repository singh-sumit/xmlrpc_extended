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

## Security context

`xmlrpc_extended` is built on Python's stdlib `xmlrpc.server`, which is **not suitable for untrusted public networks**.

**Safe deployment guidelines:**
- Run only on `localhost` or private/internal networks.
- Place behind a reverse proxy with TLS termination and authentication.
- Never set `allow_dotted_names=True` on handlers exposed to untrusted clients — this enables arbitrary attribute traversal.
- Always configure `max_request_size` to limit payload sizes.
- Prefer explicit `rpc_paths` to restrict which URL paths accept XML-RPC requests.
