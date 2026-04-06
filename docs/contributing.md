# Contributing

Thank you for your interest in contributing to `xmlrpc_extended`!

## Code of conduct

Please read and follow the [Code of Conduct](code-of-conduct.md).

## Reporting security issues

Do **not** open public issues for security vulnerabilities.
See [Security](security.md) for the private reporting process.

## Opening issues

- Search existing issues before opening a new one.
- Use the issue templates provided (bug report, feature request).
- For bugs, include the Python version, OS, and a minimal reproducible example.

## Development workflow

1. Fork the repository and create a branch from `main`.
2. Write tests first (TDD) — all behavior changes must include tests.
3. Ensure all tests pass locally before opening a PR.
4. Open a pull request against `main` with a clear description.

## Setting up your development environment

```bash
# 1. Clone and create a virtual environment
git clone https://github.com/singh-sumit/xmlrpc_extended.git
cd xmlrpc_extended
python -m venv .venv && source .venv/bin/activate

# 2. Install dev dependencies (pre-commit, ruff, mypy, build)
pip install -e ".[dev]"

# 3. Install pre-commit hooks (runs on every git commit automatically)
pre-commit install
```

## Pre-commit hooks

This project uses [pre-commit](https://pre-commit.com/) to enforce code quality
before every commit. After running `pre-commit install`, the following checks
run automatically on `git commit`:

| Hook | What it checks |
|------|---------------|
| `trailing-whitespace` | No trailing spaces |
| `end-of-file-fixer` | Files end with a newline |
| `check-yaml` / `check-toml` | Valid YAML/TOML syntax |
| `debug-statements` | No accidental `breakpoint()` / `pdb` calls |
| `ruff` | Lint with auto-fix |
| `ruff-format` | Code formatting |
| `mypy` | Strict type checking on `src/` |

Run all hooks manually:

```bash
pre-commit run --all-files
```

Update hook versions:

```bash
pre-commit autoupdate
```

## Linting and type checking

```bash
# Lint (with auto-fix for safe issues)
ruff check --fix src tests

# Formatter
ruff format src tests

# Type check
mypy src
```

## Running tests

```bash
python -m unittest discover -s tests -v
```

Expected: **45 tests pass, 1 skipped** (the `SO_REUSEPORT` test skips on non-Linux).

## Build dependencies

| Dependency   | Minimum version | Justification |
|--------------|-----------------|---------------|
| `setuptools` | `>= 64`        | First version with full PEP 621 (`[project]` table in `pyproject.toml`) and `[tool.setuptools.packages.find]` support. |

## Local build validation

```bash
# Build sdist and wheel
pip install build
python -m build

# Install from wheel and run tests
pip install dist/*.whl --no-deps
python -m unittest discover -s tests -v
```

## Docs preview

```bash
pip install -e ".[docs]"
mkdocs serve
```

## Release process

1. Update `CHANGELOG.md` under `[Unreleased]`.
2. Bump the version in `pyproject.toml`.
3. Create a GitHub release — the CI release workflow publishes to PyPI automatically.

## Questions

Open a [GitHub Discussion](https://github.com/singh-sumit/xmlrpc_extended/discussions)
for questions that don't fit an issue.
