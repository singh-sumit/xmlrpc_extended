# Contributing

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
