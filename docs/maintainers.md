# Maintainers Guide

Internal reference for project maintainers — release preparation, docs deployment, CI, and post-release tasks.

---

## Release checklist

### 1. Decide the version number

Follow [Semantic Versioning](https://semver.org/):

| Change type | Version part to bump |
|-------------|---------------------|
| Backwards-incompatible API change | `MAJOR` (x.0.0) |
| New backwards-compatible feature | `MINOR` (0.x.0) |
| Bug fix, docs, or internal change | `PATCH` (0.0.x) |

### 2. Bump the version

The version lives in exactly one place:

```toml
# pyproject.toml
[project]
version = "0.2.0"   # ← edit this
```

### 3. Update `CHANGELOG.md`

Rename the `[Unreleased]` heading to the concrete version and date and add a
fresh empty `[Unreleased]` block above it:

```markdown
## [Unreleased]

## [0.2.0] - YYYY-MM-DD

### Added
- …

### Fixed
- …
```

Update the comparison links at the bottom of the file:

```markdown
[Unreleased]: https://github.com/singh-sumit/xmlrpc_extended/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/singh-sumit/xmlrpc_extended/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/singh-sumit/xmlrpc_extended/releases/tag/v0.1.0
```

### 4. Pass all quality gates locally

Run every check before pushing:

```bash
# Lint
ruff check src tests

# Type check
mypy src

# Full test suite — 100% coverage required
python -m coverage run --source=src -m pytest tests/
python -m coverage report

# Docs build (strict mode catches broken links and missing nav entries)
mkdocs build --strict
```

All commands must exit with code 0.

### 5. Commit and push

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore: prepare v0.2.0 release"
git push origin main
```

Wait for the [CI workflow](https://github.com/singh-sumit/xmlrpc_extended/actions/workflows/ci.yml)
to go green before tagging.

### 6. Tag and publish

```bash
git tag -a v0.2.0 -m "Release v0.2.0"
git push origin v0.2.0
```

Pushing the tag triggers the [Publish workflow](#publish-workflow-publishyml) automatically.

---

## Automated CI/CD

There are three GitHub Actions workflows:

| Workflow file | Trigger | What it does |
|---------------|---------|-------------|
| `ci.yml` | Push / PR to `main` | Ruff lint → mypy → tests on Python 3.10–3.13, build wheel & sdist, install and re-test |
| `docs.yml` | Push to `main` | `mkdocs gh-deploy --force` → pushes built site to `gh-pages` branch |
| `publish.yml` | Push a `v*.*.*` tag, or `workflow_dispatch` | Build → publish to TestPyPI → verify install → publish to PyPI |

### CI workflow (`ci.yml`)

Three parallel jobs:

- **lint** — `ruff check src tests`
- **typecheck** — `mypy src`
- **test** — matrix over Python 3.10, 3.11, 3.12, 3.13:
    1. Build wheel + sdist with `python -m build`
    2. Install wheel `--no-deps` then install `httpx anyio`
    3. Run `pytest tests/` (must pass with 0 failures)
    4. Install from sdist and re-run tests

### Docs workflow (`docs.yml`)

Runs on every push to `main`. Uses `mkdocs gh-deploy --force` which:

1. Builds the static site into a temporary directory
2. Force-pushes it to the `gh-pages` branch
3. GitHub Pages serves it at <https://singh-sumit.github.io/xmlrpc_extended/>

The site is **not** rebuilt on tag pushes — only on `main` commits. If you want
to preview a doc change before merging, use `mkdocs serve` locally (see below).

### Publish workflow (`publish.yml`)

Four jobs executed in this order:

```
build  ──►  publish-testpypi  ──►  verify-testpypi
  │
  └─────►  publish-pypi  (tag pushes only)
```

`publish-pypi` depends on `build` only — not on `verify-testpypi`. This means a
TestPyPI failure (such as the [filename-reuse rule](https://test.pypi.org/help/#file-name-reuse)
that applies when a same-version file was previously uploaded and deleted) does
**not** block the real PyPI release.

Required repository secrets (Settings → Secrets and variables → Actions):

| Secret name | Value |
|-------------|-------|
| `TESTPYPI_API_TOKEN` | API token from <https://test.pypi.org> (`pypi-…`) |
| `PYPI_API_TOKEN` | API token from <https://pypi.org> (`pypi-…`) |

To trigger a publish run without creating a tag (dry-run — TestPyPI only,
PyPI step is skipped):

```bash
gh workflow run publish.yml --ref main
```

---

## Building and previewing docs locally

### Preview with live reload

```bash
# Install doc dependencies (once)
pip install -e ".[docs]"

# Start the dev server
mkdocs serve
```

Open <http://127.0.0.1:8000>. The page auto-reloads on every file save.

### Strict build (same as CI)

```bash
mkdocs build --strict
```

`--strict` turns warnings into errors. Use this before pushing doc changes to
catch broken links, missing `nav` entries, and invalid `mkdocstrings` references.
The built site lands in `site/` (`.gitignore`d).

### Force-deploy manually

If the `docs.yml` GitHub Actions run failed or you need to push docs
independently of a code commit:

```bash
mkdocs gh-deploy --force
```

This requires `contents: write` permission on the repository (already granted
in `docs.yml`). Running it locally needs a `git push` credential with write access
to the repo.

---

## Creating a GitHub Release

After the tag is pushed and the Publish workflow is green:

1. Go to <https://github.com/singh-sumit/xmlrpc_extended/releases/new>
2. Select the tag (e.g. `v0.2.0`)
3. Title: `v0.2.0`
4. Body: paste the CHANGELOG section for this version
5. Click **Publish release**

The release page links to the source tarball and the commit, and appears in the
GitHub feed for watchers.

---

## Post-release

- [ ] Confirm the package is live: `pip index versions xmlrpc-extended`
- [ ] Confirm the docs site updated: <https://singh-sumit.github.io/xmlrpc_extended/>
- [ ] Create the GitHub Release (see above)
- [ ] Open a new issue or milestone for the next version if there is work queued
- [ ] Update `pyproject.toml` version to the next development version (optional — only if you follow `-dev` suffixes)
