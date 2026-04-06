# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-04-06

### Added
- `XMLRPCASGIApp` — ASGI 3-compliant XML-RPC adapter (`src/xmlrpc_extended/asgi.py`):
  - Inherits `SimpleXMLRPCDispatcher` for full `register_function` / `register_instance` / `register_introspection_functions` compatibility.
  - `async def` handlers are awaited directly in the event loop (no thread overhead).
  - Synchronous handlers run in a `ThreadPoolExecutor` via `asyncio.to_thread`.
  - ASGI lifespan protocol: startup creates the thread pool, shutdown drains it gracefully.
  - Configurable `max_workers`, `max_request_size`, `rpc_path`, `allow_none`, `encoding`, `use_builtin_types`.
  - HTTP semantics: `404` for wrong path, `405` for non-POST, `413` for oversized body, `-32700` fault for malformed XML.
  - Zero runtime dependencies — pure stdlib + asyncio.
- `ThreadPoolXMLRPCServer` for drop-in `SimpleXMLRPCServer`-style usage with bounded thread-pool concurrency.
- `ServerOverloadPolicy` enum with `BLOCK`, `CLOSE`, `FAULT`, and `HTTP_503` modes.
- `XMLRPCServerConfig` dataclass for server configuration.
- `LimitedXMLRPCRequestHandler` with configurable `max_request_size` and strict `Content-Length` validation:
  - `411 Length Required` when `Content-Length` header is absent.
  - `400 Bad Request` for invalid or negative `Content-Length` values.
  - `413 Payload Too Large` when body exceeds `max_request_size`.
  - `501 Not Implemented` for `Transfer-Encoding: chunked` requests.
- `XMLRPCClient` context manager with configurable timeout (`xmlrpc_extended.client`).
- `SO_REUSEPORT` multi-process scale-out helpers for Linux (`xmlrpc_extended.multiprocess`).
- `logRequests=False` suppresses both request and error-path log output.
- `tests/test_asgi.py` — 45 tests following AAA pattern covering: smoke, call semantics, HTTP semantics, lifespan, dispatch edge-cases, introspection, error handling, and concurrency.
- `tests/test_server.py` — `CoverageGapTests` class with 9 new tests closing all coverage gaps in `server.py`; full `ConstructorValidationTests` and `ExecutorShutdownTests`.
- `tests/test_extras.py` — tests for `client.py` and `multiprocess.py` covering all branches.
- `benchmarks/benchmark_all.py` — unified benchmark comparing all four implementations (Simple, Threaded, ThreadPool, ASGI) side by side.
- `benchmarks/benchmark_asgi.py` — in-process ASGI benchmark using `httpx.ASGITransport`.
- `benchmarks/benchmark_server.py` — `SimpleXMLRPCServer` vs `ThreadPoolXMLRPCServer` benchmark.
- `docs/user-guide/asgi.md` — full ASGI integration guide with deployment recipes, migration table, and testing patterns.
- `docs/api-reference/asgi.md` — API reference for `XMLRPCASGIApp`.
- `docs/architecture.md` — ASGI request lifecycle sequence diagram, handler dispatch flowchart, lifespan state diagram, and architecture comparison diagram.
- `docs/benchmarks.md` — unified four-implementation benchmark results.
- `[tool.coverage.*]` in `pyproject.toml` — branch coverage, fail-under=100, HTML report config.
- AAA (Arrange-Act-Assert) comment pattern applied to all test methods.
- MIT license, packaging metadata, and CI workflow.

### Changed
- Overload semantics: capacity model table, policy behavior matrix, and recommended defaults documented in README.

[Unreleased]: https://github.com/singh-sumit/xmlrpc_extended/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/singh-sumit/xmlrpc_extended/releases/tag/v0.1.0
