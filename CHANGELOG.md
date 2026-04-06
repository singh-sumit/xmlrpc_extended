# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `XMLRPCASGIApp` — ASGI 3-compliant XML-RPC adapter (`src/xmlrpc_extended/asgi.py`):
  - Inherits `SimpleXMLRPCDispatcher` for full `register_function` / `register_instance` / `register_introspection_functions` compatibility.
  - `async def` handlers are awaited directly in the event loop (no thread overhead).
  - Synchronous handlers run in a `ThreadPoolExecutor` via `asyncio.to_thread`.
  - ASGI lifespan protocol: startup creates the thread pool, shutdown drains it gracefully.
  - Configurable `max_workers`, `max_request_size`, `rpc_path`, `allow_none`, `encoding`, `use_builtin_types`.
  - HTTP semantics: `404` for wrong path, `405` for non-POST, `413` for oversized body, `-32700` fault for malformed XML.
  - Zero runtime dependencies — pure stdlib + asyncio.
- `tests/test_asgi.py` — 45 tests following AAA pattern covering: smoke, call semantics, HTTP semantics, lifespan, dispatch edge-cases, introspection, error handling, and concurrency.
- `benchmarks/benchmark_asgi.py` — in-process ASGI benchmark using `httpx.ASGITransport`.
- `docs/user-guide/asgi.md` — full ASGI integration guide with deployment recipes, migration table, and testing patterns.
- `docs/api-reference/asgi.md` — API reference for `XMLRPCASGIApp`.
- `docs/architecture.md` — ASGI request lifecycle sequence diagram, handler dispatch flowchart, lifespan state diagram, and architecture comparison diagram.
- `docs/benchmarks.md` — ASGI benchmark results section.
- `[tool.coverage.*]` in `pyproject.toml` — branch coverage, fail-under=100, HTML report config.
- `coverage`, `httpx`, `anyio` added to `[project.optional-dependencies.dev]`.
- `CoverageGapTests` in `test_server.py` — 9 new tests closing all prior coverage gaps in `server.py`.
- `test_extras.py` — 2 new tests closing coverage gaps in `multiprocess.py` and `client.py`.
- AAA (Arrange-Act-Assert) comment pattern applied to all test methods.

### Changed
- `ConstructorValidationTests`: 13 new tests covering invalid `max_workers`, `max_pending`, `request_queue_size`, `max_request_size`, custom fault code/string, `bind_and_activate=False`, `allow_none`, `use_builtin_types`, and policy string normalization.
- `ExecutorShutdownTests`: tests for `shutdown_executor` idempotency and custom fault response.
- README: overload semantics section with capacity model table, policy behavior matrix, and recommended defaults.

## [0.1.0] - 2026-04-06

### Added
- `ThreadPoolXMLRPCServer` for drop-in `SimpleXMLRPCServer`-style usage with bounded thread-pool concurrency.
- `ServerOverloadPolicy` enum with `BLOCK`, `CLOSE`, and `FAULT` modes.
- `XMLRPCServerConfig` dataclass for server configuration.
- `LimitedXMLRPCRequestHandler` with configurable `max_request_size` and strict `Content-Length` validation:
  - `411 Length Required` when `Content-Length` header is absent.
  - `400 Bad Request` for invalid or negative `Content-Length` values.
  - `413 Payload Too Large` when body exceeds `max_request_size`.
  - `501 Not Implemented` for `Transfer-Encoding: chunked` requests.
- `logRequests=False` suppresses both request and error-path log output.
- MIT license, packaging metadata, and CI workflow.
