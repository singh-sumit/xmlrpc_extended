# Publishing `xmlrpc_extended` to PyPI

A step-by-step guide for first-time PyPI releases.

---

## Overview

Publishing a Python package to PyPI involves these stages:

1. [Account setup](#1-account-setup) — create accounts on TestPyPI and PyPI
2. [API tokens](#2-create-api-tokens) — create upload credentials
3. [Configure credentials](#3-store-credentials-locally) — store them locally
4. [Install publishing tools](#4-install-publishing-tools)
5. [Pre-release checklist](#5-pre-release-checklist) — version, changelog, quality gates
6. [Build the distributions](#6-build-the-distributions)
7. [Inspect the build](#7-inspect-the-build)
8. [Test on TestPyPI first](#8-test-upload-to-testpypi)
9. [Publish to the real PyPI](#9-publish-to-pypi)
10. [Tag the release on GitHub](#10-tag-the-release-on-github)
11. [After release](#11-after-release)

---

## 1. Account setup

You need two separate accounts — a test registry and the real one.

### TestPyPI (practice registry)

1. Go to <https://test.pypi.org/account/register/>
2. Fill in username, email, and password
3. Verify your email address

### PyPI (the real registry)

1. Go to <https://pypi.org/account/register/>
2. Fill in username, email, and password
3. Verify your email address

> **Why TestPyPI?** Uploads to PyPI are permanent — you can never delete a
> release or re-upload the same version. TestPyPI lets you rehearse the entire
> process with zero consequences.

---

## 2. Create API tokens

PyPI no longer accepts plain username + password for uploads. You must use
API tokens.

### On TestPyPI

1. Log in at <https://test.pypi.org>
2. Click your username (top right) → **Account settings**
3. Scroll to **API tokens** → **Add API token**
4. Name it something like `xmlrpc_extended-testpypi`
5. **Scope → Entire account** (first upload; switch to project scope after)
6. Click **Add token** — copy the token immediately, it is shown only once

### On PyPI

Repeat the same steps at <https://pypi.org>.

> Save both tokens somewhere safe (a password manager). They look like:
> `pypi-AgEIcHlwaS5vcmcA...`

---

## 3. Store credentials locally

The standard way is a `~/.pypirc` file. Create it with your editor:

```ini
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-AgEI...YOUR-REAL-PYPI-TOKEN...

[testpypi]
username = __token__
password = pypi-AgEI...YOUR-TESTPYPI-TOKEN...
```

Lock down the file permissions so only your user can read it:

```console
chmod 600 ~/.pypirc
```

> `username` must literally be `__token__` — that is not a placeholder.
> The token itself goes in `password`.

---

## 4. Install publishing tools

```console
# Activate the project virtual environment first
source .venv/bin/activate

# build    — creates sdist + wheel
# twine    — uploads to PyPI, validates the package beforehand
# check-wheel-contents — catches common wheel packaging mistakes (optional)
pip install "build>=1.2" "twine>=5.0" "check-wheel-contents>=0.6"
```

`build` is already listed in `[project.optional-dependencies.dev]` in
`pyproject.toml` so it is already installed if you ran `pip install -e ".[dev]"`.
Only `twine` needs to be added.

---

## 5. Pre-release checklist

Work through every item before building:

### 5a. Pick a version number

The project follows [Semantic Versioning](https://semver.org/):

| Part | When to increment |
|------|------------------|
| **MAJOR** (x.0.0) | Incompatible API change |
| **MINOR** (0.x.0) | New backwards-compatible feature |
| **PATCH** (0.0.x) | Backwards-compatible bug fix |

For the **first public release** use `0.1.0`.

The version lives in one place only:

```toml
# pyproject.toml
[project]
version = "0.1.0"
```

### 5b. Update `CHANGELOG.md`

The current `CHANGELOG.md` has everything under `[Unreleased]`. Before
releasing, rename that heading to the concrete version and date, then add
a fresh empty `[Unreleased]` section above it:

```markdown
## [Unreleased]

## [0.1.0] - 2026-04-XX

### Added
...existing entries...
```

Also add the comparison links at the very bottom of the file (Keep a
Changelog convention):

```markdown
[Unreleased]: https://github.com/singh-sumit/xmlrpc_extended/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/singh-sumit/xmlrpc_extended/releases/tag/v0.1.0
```

### 5c. Pass all quality gates

```console
# Lint
ruff check src tests

# Type check
mypy src

# Full test suite with coverage
python -m coverage run --source=src -m pytest tests/
python -m coverage report
# Expected: 103 passed, 1 skipped, 100% coverage

# Docs build
mkdocs build --strict
```

All commands must exit with code 0.

### 5d. Commit everything

```console
git add pyproject.toml CHANGELOG.md
git commit -m "chore: prepare v0.1.0 release"
git push origin main
```

Wait for the CI workflow to go green before continuing.

---

## 6. Build the distributions

First, remove any stale build artifacts:

```console
rm -rf dist/ build/ src/*.egg-info/
```

Then build:

```console
python -m build
```

This produces two files in `dist/`:

```
dist/
  xmlrpc_extended-0.1.0-py3-none-any.whl   ← binary wheel (installs fast)
  xmlrpc_extended-0.1.0.tar.gz              ← source distribution (sdist)
```

You must upload **both** — the wheel for fast installs, the sdist so pip can
build from source on platforms without a matching wheel.

---

## 7. Inspect the build

### Check the wheel contents

```console
check-wheel-contents dist/xmlrpc_extended-0.1.0-py3-none-any.whl
```

Expected output: `All checks passed!`

### Validate with twine

```console
twine check dist/*
```

`twine check` parses the sdist and wheel metadata and renders the README to
catch any reStructuredText or Markdown errors before upload.

Expected output:
```
Checking dist/xmlrpc_extended-0.1.0-py3-none-any.whl: PASSED
Checking dist/xmlrpc_extended-0.1.0.tar.gz: PASSED
```

### Inspect the wheel manually (optional)

A `.whl` file is just a zip archive:

```console
unzip -l dist/xmlrpc_extended-0.1.0-py3-none-any.whl
```

Verify you see:
- `xmlrpc_extended/__init__.py`
- `xmlrpc_extended/server.py`
- `xmlrpc_extended/client.py`
- `xmlrpc_extended/multiprocess.py`
- `xmlrpc_extended/asgi.py`
- `xmlrpc_extended/py.typed`
- The `METADATA` and `RECORD` files inside `xmlrpc_extended-0.1.0.dist-info/`

### Sanity-install the wheel in a fresh venv

```console
python -m venv /tmp/test-install
/tmp/test-install/bin/pip install dist/xmlrpc_extended-0.1.0-py3-none-any.whl --no-deps
/tmp/test-install/bin/python -c "from xmlrpc_extended import ThreadPoolXMLRPCServer; print('OK')"
```

---

## 8. Test upload to TestPyPI

```console
twine upload --repository testpypi dist/*
```

Twine reads `~/.pypirc` automatically. You will see output like:

```
Uploading distributions to https://test.pypi.org/legacy/
Uploading xmlrpc_extended-0.1.0-py3-none-any.whl
100% ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 17.4 kB
Uploading xmlrpc_extended-0.1.0.tar.gz
100% ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 20.1 kB

View at:
https://test.pypi.org/project/xmlrpc_extended/0.1.0/
```

### Verify on TestPyPI

1. Open the URL shown in the output in your browser.
2. Check that the project description (README) renders correctly.
3. Check the metadata: version, author, license, classifiers, links.

### Test-install from TestPyPI

```console
python -m venv /tmp/testpypi-install
/tmp/testpypi-install/bin/pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  xmlrpc_extended
/tmp/testpypi-install/bin/python -c "
from xmlrpc_extended import ThreadPoolXMLRPCServer, ServerOverloadPolicy
from xmlrpc_extended.asgi import XMLRPCASGIApp
print('core import OK')
print('asgi import OK')
"
```

> `--extra-index-url https://pypi.org/simple/` is needed because TestPyPI
> does not mirror the real PyPI — any dependency (even standard ones) must
> fall back to the real index.

---

## 9. Publish to PyPI

Once TestPyPI looks correct, the real upload is a single command — just omit
`--repository testpypi`:

```console
twine upload dist/*
```

Expected output:

```
Uploading distributions to https://upload.pypi.org/legacy/
Uploading xmlrpc_extended-0.1.0-py3-none-any.whl
100% ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 17.4 kB
Uploading xmlrpc_extended-0.1.0.tar.gz
100% ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 20.1 kB

View at:
https://pypi.org/project/xmlrpc-extended/0.1.0/
```

The package is now publicly installable:

```console
pip install xmlrpc-extended
```

> **This cannot be undone.** You can never re-upload the same version number,
> and PyPI does not allow deleting releases. If you discover a critical mistake,
> your only option is to upload a new patch version (e.g. `0.1.1`).

---

## 10. Tag the release on GitHub

Create an annotated git tag that matches the version:

```console
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

Then create a GitHub Release:

1. Go to <https://github.com/singh-sumit/xmlrpc_extended/releases/new>
2. **Tag** → choose `v0.1.0`
3. **Release title**: `v0.1.0`
4. **Description**: paste the `[0.1.0]` section from `CHANGELOG.md`
5. Click **Publish release**

GitHub will automatically attach the zip/tar.gz source archives. If you want
to attach the wheel and sdist too, drag them into the release assets section.

---

## 11. After release

### Verify the published package

```console
pip install xmlrpc-extended==0.1.0
python -c "import xmlrpc_extended; print(xmlrpc_extended.__version__)"
```

### Check the PyPI page

<https://pypi.org/project/xmlrpc-extended/> — confirm:
- Version badge shows `0.1.0`
- Description (README) renders correctly
- Links to GitHub, Issues, Changelog, Discussions all work
- Classifiers look correct

### Update the badge in README (if not already set)

The CI badge (`[![CI]...]`) uses a dynamic status from GitHub Actions and
updates automatically. You may want to add a PyPI version badge:

```markdown
[![PyPI](https://img.shields.io/pypi/v/xmlrpc-extended)](https://pypi.org/project/xmlrpc-extended/)
```

### Prepare for the next cycle

Add a scoped API token for future releases (scope it to just the
`xmlrpc-extended` project instead of "entire account"):

1. PyPI → Account settings → API tokens → Add API token
2. Scope: **Project `xmlrpc-extended`**
3. Update `~/.pypirc` with the new narrower token

Start the next development cycle in `CHANGELOG.md`:

```markdown
## [Unreleased]

## [0.1.0] - 2026-04-XX
...
```

---

## 12. Automated releases via GitHub Actions

The repository ships `.github/workflows/publish.yml` which automates the
entire release pipeline. You only need to add two secrets once.

### Add GitHub secrets

Go to **Settings → Secrets and variables → Actions → New repository secret**
at <https://github.com/singh-sumit/xmlrpc_extended/settings/secrets/actions>
and add:

| Secret name | Value |
|---|---|
| `TESTPYPI_API_TOKEN` | Your TestPyPI API token (starts with `pypi-`) |
| `PYPI_API_TOKEN` | Your PyPI API token (starts with `pypi-`) |

### Create GitHub Environments (recommended)

GitHub Environments add an optional manual approval gate before production:

1. Go to **Settings → Environments → New environment**
2. Create `testpypi` (no protection rules needed)
3. Create `pypi` → add **Required reviewers** (yourself) so the real-PyPI
   step always pauses for confirmation

### How the workflow runs

```
push tag v0.1.0
     │
     ▼
 build              ← python -m build + check-wheel-contents + twine check
     │
     ▼
 publish-testpypi   ← twine upload → test.pypi.org
     │
     ▼
 verify-testpypi    ← pip install from TestPyPI + import smoke-test
     │
     ▼
 publish-pypi       ← twine upload → pypi.org  (tag pushes only, skipped on
                                                 workflow_dispatch)
```

### Trigger a dry-run (TestPyPI only)

```console
# In GitHub UI: Actions → Publish → Run workflow
# This runs all steps except the final PyPI upload.
```

### Trigger a real release

```console
# Commit your release prep (version bump, CHANGELOG update)
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

The tag push triggers the full pipeline. Monitor it at
<https://github.com/singh-sumit/xmlrpc_extended/actions>.

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `403 Forbidden` | Wrong token or wrong `username` | `username` must be `__token__`; re-copy the token |
| `400 File already exists` | Version was already uploaded | Bump the version in `pyproject.toml` and rebuild |
| `twine check` fails | README has Markdown/RST syntax errors | Fix the README and rebuild |
| `Invalid distribution file` | Building on dirty tree | `rm -rf dist/ build/` then rebuild |
| Package installs but import fails | Source files not included in wheel | Check `[tool.setuptools.packages.find]` in `pyproject.toml` |
| TestPyPI install fails on dependencies | TestPyPI doesn't mirror PyPI deps | Add `--extra-index-url https://pypi.org/simple/` |

---

## Reference commands (quick copy-paste)

```bash
# 0. Install tools
pip install "twine>=5.0" "check-wheel-contents>=0.6"

# 1. Quality gates
ruff check src tests && mypy src
python -m coverage run --source=src -m pytest tests/ && python -m coverage report
mkdocs build --strict

# 2. Clean + build
rm -rf dist/ build/ src/*.egg-info/
python -m build

# 3. Validate
check-wheel-contents dist/*.whl
twine check dist/*

# 4. TestPyPI
twine upload --repository testpypi dist/*

# 5. Real PyPI
twine upload dist/*

# 6. Tag
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```
