# GitHub Copilot Instructions — xmlrpc_extended

> Workspace-level instructions for GitHub Copilot (VS Code extension and
> Copilot Chat).  These complement `AGENTS.md` which contains the full
> project context.

---

## Project at a glance

- **Package:** `xmlrpc_extended` — thread-pool extension for Python's stdlib `SimpleXMLRPCServer`
- **Layout:** `src/` layout, `tests/`, `benchmarks/`, `docs/`
- **No runtime dependencies** — pure stdlib
- **Python:** 3.10+ (use `from __future__ import annotations`)
- **Lint:** `ruff` (rules E, F, W, I, UP; line-length 120)
- **Types:** `mypy --strict` on `src/`

---

## Key files

| File | Purpose |
|------|---------|
| `src/xmlrpc_extended/server.py` | Core server; `ThreadPoolXMLRPCServer`, policies, stats |
| `src/xmlrpc_extended/client.py` | `XMLRPCClient` context manager |
| `src/xmlrpc_extended/multiprocess.py` | `SO_REUSEPORT` helpers (Linux only) |
| `tests/test_server.py` | 45 unit tests for server |
| `tests/test_extras.py` | Tests for client and multiprocess |
| `AGENTS.md` | Full AI agent instructions (read this first) |

---

## Workflow cues for Copilot

### When editing `src/`

- Always check `mypy src` passes after changes
- Run `ruff check --fix src tests` before presenting code
- Use `collections.abc.Callable` not `typing.Callable` (UP035)
- Frozen dataclasses for value objects; `threading.Lock` for shared state

### When adding a test

- Follow the `setUp`/`tearDown` pattern in `test_server.py`
- Use `("127.0.0.1", 0)` — port 0 lets the OS pick a free port
- Add `time.sleep(0.05)` before asserting on async counter changes
- `tearDown` must call `server.shutdown()` then `server.server_close()` then `thread.join(timeout=5)`

### When adding docs

- Docs source is in `docs/` (MkDocs Material)
- Run `mkdocs serve` to preview
- Mermaid diagrams go in fenced ` ```mermaid ` blocks
- Use admonitions (`!!! tip`, `!!! warning`, `!!! danger`) for callouts
- No email addresses anywhere in docs — use the [Discussions link](https://github.com/singh-sumit/xmlrpc_extended/discussions)

### Common commands

```bash
# Tests
python -m unittest discover -s tests -v

# Lint + format
ruff check --fix src tests && ruff format src tests

# Type check
mypy src

# All in one (pre-commit)
pre-commit run --all-files

# Docs preview
mkdocs serve

# Docs build (strict)
mkdocs build --strict
```

---

## Things to never do

- Do not add runtime dependencies (`requirements.txt`, `install_requires`)
- Do not use `threading.Thread` subclasses — use `ThreadPoolExecutor` instead
- Do not expose `allow_dotted_names=True` in any example code
- Do not retry XML-RPC calls automatically — methods may not be idempotent
- Do not change `ServerOverloadPolicy` string values (config-file compatibility)
- Do not add `time.sleep` to production code (tests and benchmarks only)

---

## Getting help

Questions about the project → [GitHub Discussions](https://github.com/singh-sumit/xmlrpc_extended/discussions)
