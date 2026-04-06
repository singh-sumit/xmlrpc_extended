# xmlrpc_extended: Issues and Milestones

This backlog is based on inspection of the uploaded `xmlrpc_extended-main.zip` repository contents, local validation of the package, and current Python/PyPI documentation.

## Repository snapshot analyzed

- `src/xmlrpc_extended/server.py`
- `src/xmlrpc_extended/__init__.py`
- `tests/test_server.py`
- `pyproject.toml`
- `README.md`
- `.github/workflows/ci.yml`

## What is already good

- Clear, focused scope: bounded thread-pool XML-RPC server.
- `src/` layout and a small public API.
- Good first-pass integration tests around concurrency, overload handling, and shutdown.
- Minimal dependency footprint.
- Thoughtful overload behavior with `BLOCK`, `CLOSE`, and `FAULT`.

## Main gaps found

1. Missing `Content-Length` currently results in HTTP 500 instead of a clean client error.
2. `logRequests=False` does not suppress error-path logging for 4xx responses.
3. Open-source release metadata is incomplete: no license metadata/file, no contributing/security docs, no changelog.
4. CI only runs unit tests; it does not lint, type-check, build sdists/wheels, or exercise release paths.
5. Typing is inline but the wheel does not include `py.typed`.
6. Documentation is still README-only; no API docs, examples, operations guide, or TDD/contributor guidance.
7. Scalability roadmap items (metrics, worker-process model, async support) are not yet planned as implementable milestones.

## Suggested milestones

### M0 — Release blockers and correctness hardening
Target: first serious OSS-ready patch release (`0.1.1`)

- Fix transport validation bugs.
- Clean up packaging metadata.
- Improve CI to validate builds.
- Add contributor and security basics.

### M1 — Test and API hardening
Target: `0.2.0`

- Expand TDD coverage for edge cases.
- Add typing marker and static checks.
- Improve request handler configurability and docs.
- Add observability counters.

### M2 — Operational maturity
Target: `0.3.0`

- Add metrics/hooks.
- Add clearer overload semantics and docs.
- Add examples and benchmark scripts.
- Add release automation for PyPI/TestPyPI.

### M3 — Scale-out features
Target: `0.4.0`

- Multi-process worker manager.
- `SO_REUSEPORT` support where supported.
- Configurable HTTP 503 rejection mode.
- Optional client helpers (timeouts/retries).

### M4 — Optional async integration
Target: `0.5.0+`

- Optional ASGI adapter.
- Clear separation between core server package and optional extras.

## Detailed issue backlog

---

### 1) Fix missing `Content-Length` handling
- **Type:** bug
- **Priority:** P0
- **Milestone:** M0
- **Labels:** `bug`, `http`, `security`, `tests`
- **Problem:** `LimitedXMLRPCRequestHandler.do_POST()` validates `Content-Length` only if present. A POST without `Content-Length` falls through to stdlib handling and returns HTTP 500.
- **Why it matters:** malformed client input should yield a 4xx response, not a server error.
- **Proposed change:** reject missing `Content-Length` with `411 Length Required` or `400 Bad Request`; explicitly reject unsupported `Transfer-Encoding: chunked` if not supported.
- **TDD tasks:**
  - add failing test for POST without `Content-Length`
  - add failing test for negative `Content-Length`
  - optionally add failing test for `Transfer-Encoding: chunked`
- **Acceptance criteria:**
  - no malformed-body case returns 500
  - tests cover missing, invalid, negative, and oversized length cases
  - README documents request-size and request-shape expectations

### 2) Honor `logRequests=False` on error paths
- **Type:** bug
- **Priority:** P1
- **Milestone:** M0
- **Labels:** `bug`, `logging`, `tests`
- **Problem:** 4xx responses from `send_error()` still write to stderr even when `logRequests=False` is passed to the server.
- **Why it matters:** this creates noisy logs and breaks expectations for embedded/service deployments.
- **Proposed change:** override request-handler logging hooks so both success and error-path logging respect the server logging configuration.
- **TDD tasks:**
  - add failing test that captures stderr for oversized payload and invalid header cases
- **Acceptance criteria:**
  - with `logRequests=False`, no request/error log lines are emitted
  - with `logRequests=True`, normal behavior is preserved

### 3) Add OSS license metadata and legal files
- **Type:** release-blocker
- **Priority:** P0
- **Milestone:** M0
- **Labels:** `packaging`, `legal`, `docs`
- **Problem:** the project currently lacks a declared license in `pyproject.toml` and does not include a `LICENSE` file.
- **Why it matters:** publishing a package without clear licensing is a blocker for adoption.
- **Proposed change:** choose a project license (for example MIT or Apache-2.0), add `LICENSE`, and declare `license` / `license-files` metadata.
- **Acceptance criteria:**
  - wheel and sdist include license file
  - package metadata shows an explicit license
  - README and repository sidebar reflect the same license

### 4) Relax or justify the strict build-system pin
- **Type:** packaging
- **Priority:** P1
- **Milestone:** M0
- **Labels:** `packaging`, `build`
- **Problem:** `pyproject.toml` requires `setuptools>=78.1.1`. In local offline validation, `pip install . --no-deps` with build isolation failed because pip attempted to fetch build dependencies, while `--no-build-isolation` succeeded.
- **Why it matters:** the current pin is harder than necessary for a tiny package and makes offline or constrained builds brittle.
- **Proposed change:** lower the minimum supported setuptools version to the minimum actually required for the chosen metadata/features, or document why the pin is needed.
- **TDD/tasks:**
  - add a build job that runs `python -m build`
  - add install-from-wheel and install-from-sdist checks
- **Acceptance criteria:**
  - build succeeds in CI for sdist and wheel
  - minimum build dependency versions are documented and justified

### 5) Add `py.typed` and package typing support explicitly
- **Type:** enhancement
- **Priority:** P1
- **Milestone:** M1
- **Labels:** `typing`, `packaging`
- **Problem:** the package uses inline type hints but does not ship `py.typed`.
- **Why it matters:** downstream type checkers will not reliably treat the distribution as typed.
- **Proposed change:** add `py.typed`, include it in package data, and document typing support.
- **Acceptance criteria:**
  - built wheel contains `xmlrpc_extended/py.typed`
  - static type-check job runs in CI

### 6) Add static quality tooling
- **Type:** maintenance
- **Priority:** P1
- **Milestone:** M1
- **Labels:** `ci`, `quality`, `typing`
- **Problem:** there is no configured linting, formatting, or type-checking step.
- **Why it matters:** the codebase is still small, which is the best time to lock in consistency.
- **Proposed change:** add `ruff` for lint/format enforcement and `mypy` or `pyright` for type checking.
- **Acceptance criteria:**
  - CI fails on lint/type regressions
  - repository includes minimal tool configuration in `pyproject.toml`

### 7) Expand TDD coverage for initialization and edge cases
- **Type:** test
- **Priority:** P1
- **Milestone:** M1
- **Labels:** `tests`, `tdd`
- **Problem:** current tests cover core behavior but miss constructor validation and several edge cases.
- **Missing tests:**
  - invalid `max_workers`, `max_pending`, `request_queue_size`, `max_request_size`
  - custom overload fault code/string
  - custom request handler class
  - `bind_and_activate=False`
  - `use_builtin_types` and `allow_none`
  - executor shutdown idempotency
  - request rejection under concurrent race conditions
- **Acceptance criteria:**
  - coverage includes constructor validation and request-handler extension points
  - tests remain deterministic on CI

### 8) Add API docs for overload semantics and queueing model
- **Type:** docs
- **Priority:** P1
- **Milestone:** M1
- **Labels:** `docs`, `api`, `operations`
- **Problem:** the README explains the feature set but not the operational semantics well enough for production users.
- **Needs documentation:**
  - difference between `max_workers`, `max_pending`, and socket backlog
  - behavior of `BLOCK`, `CLOSE`, and `FAULT`
  - recommended defaults for embedded vs service deployments
- **Acceptance criteria:**
  - README includes a behavior matrix
  - docs explain latency/throughput trade-offs with examples

### 9) Revisit the default `max_pending` behavior
- **Type:** design
- **Priority:** P2
- **Milestone:** M1
- **Labels:** `design`, `api`
- **Problem:** `max_pending=None` becomes `max_workers`, which silently enables a queue equal to the worker count.
- **Why it matters:** for latency-sensitive systems, default queuing may hide overload rather than fail fast.
- **Proposed change:** document this default immediately; consider changing the default to `0` in the next breaking release, or introduce a named policy preset.
- **Acceptance criteria:**
  - explicit ADR or design note on default pending behavior
  - no ambiguity in docs or constructor docstring

### 10) Make request path restriction configurable and safer by default
- **Type:** enhancement
- **Priority:** P2
- **Milestone:** M1
- **Labels:** `security`, `api`, `docs`
- **Problem:** the package currently relies on stdlib handler defaults rather than offering a first-class `rpc_paths` configuration.
- **Why it matters:** production deployments often want `/RPC2` or another explicit path only.
- **Proposed change:** add constructor/config support for `rpc_paths`, with docs recommending a restricted path.
- **Acceptance criteria:**
  - users can pass an RPC path tuple without subclassing the handler
  - tests verify 404 behavior for disallowed paths

### 11) Add public stats/metrics hooks
- **Type:** enhancement
- **Priority:** P1
- **Milestone:** M2
- **Labels:** `observability`, `metrics`
- **Problem:** there is no built-in way to inspect active requests, queued requests, or rejected requests.
- **Why it matters:** overload tuning without metrics is guesswork.
- **Proposed change:** add counters such as active, queued, rejected-close, rejected-fault, completed, and errored; expose a `snapshot()` API or callback hooks.
- **Acceptance criteria:**
  - tests verify counters change correctly under load
  - examples show how to export metrics to logs or Prometheus-style collectors

### 12) Add benchmark and load-test scripts
- **Type:** tooling
- **Priority:** P2
- **Milestone:** M2
- **Labels:** `benchmark`, `docs`, `perf`
- **Problem:** the project makes performance-oriented claims but ships no benchmark or reproducible load scripts.
- **Proposed change:** add a small benchmark harness comparing stdlib `SimpleXMLRPCServer` with `ThreadPoolXMLRPCServer` under slow-handler and mixed-load scenarios.
- **Acceptance criteria:**
  - benchmark scripts are runnable locally
  - docs include caveats and interpretation guidance

### 13) Add contributor-facing OSS docs
- **Type:** docs
- **Priority:** P0
- **Milestone:** M0
- **Labels:** `docs`, `community`
- **Needed files:**
  - `CONTRIBUTING.md`
  - `CHANGELOG.md`
  - `SECURITY.md`
  - `CODE_OF_CONDUCT.md`
  - issue templates and PR template
- **Acceptance criteria:**
  - repository is contributor-ready
  - release notes process is documented
  - security reporting path is explicit

### 14) Strengthen CI to build, lint, type-check, and test wheels/sdists
- **Type:** CI
- **Priority:** P0
- **Milestone:** M0
- **Labels:** `ci`, `packaging`, `release`
- **Problem:** current CI only installs and runs tests on Ubuntu for Python 3.10–3.12.
- **Proposed change:**
  - add lint job
  - add type-check job
  - add build job (`python -m build`)
  - add install-from-wheel and install-from-sdist job
  - add 3.13 to the test matrix
  - optionally add Windows and macOS smoke tests
- **Acceptance criteria:**
  - CI validates the exact artifacts that will be published
  - badges/documentation reflect supported Python versions

### 15) Add release workflow for TestPyPI/PyPI trusted publishing
- **Type:** release
- **Priority:** P1
- **Milestone:** M2
- **Labels:** `release`, `pypi`, `github-actions`
- **Problem:** there is no automated release pipeline.
- **Proposed change:** add a release workflow that builds distributions, optionally publishes to TestPyPI on tags/pre-releases, and publishes to PyPI via trusted publishing on releases.
- **Acceptance criteria:**
  - repository contains a release workflow
  - maintainers can perform a dry run against TestPyPI
  - release steps are documented in `CONTRIBUTING.md`

### 16) Add explicit security posture and safe-usage guide
- **Type:** docs
- **Priority:** P1
- **Milestone:** M2
- **Labels:** `security`, `docs`
- **Problem:** the README mentions security briefly, but not in enough depth for new users.
- **Guide should cover:**
  - stdlib XML-RPC trust boundaries
  - localhost/private network recommendations
  - TLS termination expectations
  - `allow_dotted_names` risks
  - request size limits and authentication guidance
- **Acceptance criteria:**
  - dedicated security page exists
  - README links to it prominently

### 17) Add multi-process worker mode with `SO_REUSEPORT`
- **Type:** feature
- **Priority:** P2
- **Milestone:** M3
- **Labels:** `scaling`, `linux`, `processes`
- **Problem:** the package currently scales within a single process only.
- **Proposed change:** add an optional worker-manager helper for Linux deployments using `SO_REUSEPORT`, while keeping the core package dependency-light.
- **Acceptance criteria:**
  - Linux-only support is clearly documented
  - tests are platform-gated
  - examples demonstrate worker-process startup

### 18) Add richer rejection modes, including HTTP 503
- **Type:** enhancement
- **Priority:** P2
- **Milestone:** M3
- **Labels:** `api`, `http`, `overload`
- **Problem:** current overload modes are useful but limited to block, connection close, and XML-RPC fault.
- **Proposed change:** add an HTTP 503 mode or configurable transport-level rejection behavior.
- **Acceptance criteria:**
  - clients can distinguish overload at transport level when desired
  - behavior is fully documented and tested

### 19) Consider optional client helpers
- **Type:** feature
- **Priority:** P3
- **Milestone:** M3
- **Labels:** `client`, `timeouts`, `retries`
- **Problem:** the package solves server-side overload, but consumers may still need consistent timeout/retry behavior.
- **Proposed change:** add a tiny optional client helper around `xmlrpc.client.ServerProxy` with timeout-aware transport and conservative retry guidance.
- **Acceptance criteria:**
  - stays optional and dependency-light
  - docs clearly distinguish transport retries from idempotency concerns

### 20) Optional ASGI adapter / async integration
- **Type:** feature
- **Priority:** P3
- **Milestone:** M4
- **Labels:** `async`, `asgi`, `future`
- **Problem:** async support is in the roadmap but not yet scoped.
- **Proposed change:** create a separate optional extra or subpackage for ASGI integration so the core package stays small.
- **Acceptance criteria:**
  - no async dependency is imposed on the core package
  - docs explain when to choose threads, worker processes, or async

## Recommended execution order

1. Fix correctness bugs (`Content-Length`, logging semantics).
2. Make the package legally and operationally publishable (license, docs, build/release CI).
3. Expand TDD coverage and typing support.
4. Add observability and better deployment docs.
5. Add scale-out features only after the contract and docs are stable.

## Suggested labels

- `bug`
- `release-blocker`
- `docs`
- `tests`
- `tdd`
- `packaging`
- `ci`
- `security`
- `typing`
- `observability`
- `scaling`
- `good first issue`

## Suggested first 5 issues to open immediately

1. Fix missing `Content-Length` handling.
2. Honor `logRequests=False` on error paths.
3. Add OSS license metadata and legal files.
4. Strengthen CI to build, lint, type-check, and test artifacts.
5. Add contributor-facing docs (`CONTRIBUTING`, `SECURITY`, `CHANGELOG`).
