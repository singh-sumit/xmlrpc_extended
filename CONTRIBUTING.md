# Contributing

Thank you for your interest in contributing to `xmlrpc_extended`!

## Code of conduct

Please read and follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Reporting security issues

Do **not** open public issues for security vulnerabilities. See [SECURITY.md](SECURITY.md) for the private reporting process.

## Opening issues

- Search existing issues before opening a new one.
- Use the issue templates provided (bug report, feature request).
- For bugs, include the Python version, OS, and a minimal reproducible example.

## Development workflow

1. Fork the repository and create a branch from `main`.
2. Write tests first (TDD) — all behavior changes must include tests.
3. Ensure all tests pass locally before opening a PR.
4. Open a pull request against `main` with a clear description.

## Build dependencies

| Dependency   | Minimum version | Justification |
|--------------|-----------------|---------------|
| `setuptools` | `>= 64`        | First version with full PEP 621 (`[project]` table in `pyproject.toml`) and `[tool.setuptools.packages.find]` support. No compiled extensions are used, so no higher version is needed. |

The project intentionally avoids a tight setuptools pin so that offline,
air-gapped, and constrained CI environments can build the package with any
setuptools release from 64 onward.

## Local validation

```bash
# Build sdist and wheel
python -m pip install build
python -m build

# Install from wheel and run tests
python -m pip install dist/*.whl --no-deps
python -m unittest discover -s tests -v

# Or install from sdist and run tests
python -m pip install dist/*.tar.gz --no-deps
python -m unittest discover -s tests -v
```

## Linting and type checking

```bash
pip install ruff mypy
ruff check src tests
mypy src
```

## Release process

Releases are tagged on `main` and published to PyPI via GitHub Actions (see `.github/workflows/`).

1. Update `CHANGELOG.md` under `[Unreleased]`.
2. Bump the version in `pyproject.toml`.
3. Create a GitHub release — the CI release workflow publishes to PyPI automatically.
