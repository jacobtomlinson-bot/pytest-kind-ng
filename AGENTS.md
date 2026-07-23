# AGENTS.md

Guidance for AI agents (and humans) working in this repository. Read this before making changes.

## What this project is

`pytest-kind-ng` is a maintained fork of [`pytest-kind`](https://codeberg.org/hjacobs/pytest-kind). It is a
[pytest](https://pytest.org) plugin that lets you test Python Kubernetes apps and operators end-to-end using
[kind](https://kind.sigs.k8s.io/) (Kubernetes IN Docker).

- **Distributed on PyPI as `pytest-kind-ng`** (the importable package is still `pytest_kind`). Do not rename the
  importable module without a deliberate release decision.
- The plugin exposes a session-scoped `kind_cluster` pytest fixture, backed by the `KindCluster` class.
- Versioning is **CalVer** (`YY.MM.MICRO`, e.g. `22.11.1`).
- License: **GPL-3.0+**.

### Layout

```
pytest_kind/
  __init__.py      # exports KindCluster
  cluster.py       # KindCluster: download kind/kubectl, create/delete cluster, kubectl, port_forward, load_docker_image
  plugin.py        # pytest fixture `kind_cluster` + CLI options (pytest_addoption)
tests/
  conftest.py      # enables the pytester plugin
  test_cluster.py  # unit-ish tests for KindCluster (test_create_delete spins up a real cluster)
  test_plugin.py   # exercises the fixture via pytester (creates a real cluster, pulls busybox)
examples/
  aiohttp-helloworld/   # sample app + e2e test showing real-world usage
.github/workflows/test.yaml   # CI (lint + test matrix)
Makefile              # install / lint / test / test.local targets
pyproject.toml        # Poetry project metadata + pytest11 plugin entry point
.pre-commit-config.yaml
.flake8
```

### Key implementation details (`pytest_kind/cluster.py`)

- Default tool versions are pinned and overridable via env vars:
  - `KIND_VERSION` (default `v0.17.0`), `KUBECTL_VERSION` (default `v1.25.3`).
  - Download URLs can be overridden with `KIND_DOWNLOAD_URL` / `KUBECTL_DOWNLOAD_URL` (used by `make test.local`).
- `kind` and `kubectl` binaries are downloaded on demand into `./.pytest-kind/{cluster-name}/` (gitignored). They are
  reused across runs.
- Cross-platform: handles the `.exe` suffix and download paths for Windows.
- `KindCluster` methods: `create(config_file=None)`, `delete()`, `load_docker_image(image)`, `kubectl(*args)`,
  `port_forward(service_or_pod, remote_port, ...)` (context manager returning a local port), plus `ensure_kind()` /
  `ensure_kubectl()`.
- `create()` is idempotent — it re-uses an existing cluster of the same name if present.

### Plugin CLI options (`pytest_kind/plugin.py`)

- `--cluster-name` (default `pytest-kind`)
- `--keep-cluster` — do not delete the cluster after the session (useful for debugging)
- `--kubeconfig` — use an existing kubeconfig instead of a generated one
- `--kind-image` — use a specific `kindest/node` image
- `--kind-bin` / `--kind-kubectl-bin` — use existing binaries instead of downloading

These can also be passed via the `PYTEST_ADDOPTS` env var (e.g. `PYTEST_ADDOPTS=--keep-cluster make test`).

## Prerequisites

- **Docker** must be installed and running — kind runs Kubernetes nodes as Docker containers. Any test that calls
  `cluster.create()` (i.e. most of the test suite, plus the examples) will fail without it.
- **Python** `>=3.7`. CI tests 3.7–3.10.
- **[Poetry](https://python-poetry.org/)** for dependency management and builds. CI pins `poetry==1.2.2`.
- Network access on first run to download the `kind` and `kubectl` binaries (unless you point at local copies via
  `--kind-bin` / env vars).

## Install

```bash
poetry install        # or: make install
```

Set up pre-commit hooks locally if you'll be committing:

```bash
poetry run pre-commit install
```

## Running the tests

The whole suite (via `make`) runs lint first, then tests under coverage:

```bash
make test             # lint + coverage run pytest + coverage report
```

Run just the tests directly:

```bash
poetry run coverage run --source=pytest_kind -m pytest tests/
poetry run coverage report
```

Run a single test:

```bash
poetry run pytest tests/test_cluster.py::test_cluster_name
```

Notes:

- `test_cluster_name` and `test_cluster_kubeconfig` are pure unit tests (no Docker needed).
- `test_create_delete` and everything in `test_plugin.py` **create real kind clusters** (need Docker) and are slow —
  cluster creation/teardown dominates wall-clock time.
- `test_plugin.py` runs `docker pull busybox`.
- To test the binary-download path against a local server, use `make test.local` (serves a `fake-download/` directory
  over HTTP and points `KIND_DOWNLOAD_URL` at it).

### Trying it out manually

Write a test that uses the fixture:

```python
def test_kubernetes_version(kind_cluster):
    assert kind_cluster.api.version == ('1', '25')
```

Or drive `KindCluster` directly without pytest:

```python
from pytest_kind import KindCluster

cluster = KindCluster("myclustername")
cluster.create()
cluster.kubectl("apply", "-f", "...")
cluster.delete()
```

See `examples/aiohttp-helloworld/` for an end-to-end example (`make test` in that directory builds a Docker image and
runs an e2e test).

## Linting

Linting is driven entirely by **pre-commit**:

```bash
make lint             # poetry run pre-commit run --all-files
```

The config (`.pre-commit-config.yaml`) includes: black, reorder-python-imports, pyupgrade, flake8 (config in
`.flake8`), mypy (with `types-requests`), bandit, pydocstyle, yamllint, safety, `poetry check`, gitlint (commit-msg
linting), and various pre-commit-hooks. Some hooks only run at the `push` stage (bandit, pyupgrade, safety).

Match existing style: black formatting, imports reordered one-per-line, type annotations on public methods, GPL/CalVer
conventions preserved.

## CI

GitHub Actions workflow: `.github/workflows/test.yaml` (runs on `pull_request`, `push`, and `workflow_dispatch`).

- **lint** job: Python 3.9, installs Poetry, runs `make lint`.
- **test** job: matrix over Python 3.7 (on `ubuntu-22.04`), 3.8, 3.9, 3.10 (on `ubuntu-latest`). Installs Poetry, runs
  `poetry install` then coverage + pytest, and dumps `docker ps --all` on failure.
- Concurrency is set to cancel in-progress runs for the same ref/PR.

CI runs on GitHub-hosted Ubuntu runners, which have Docker available, so the real-cluster tests execute there.

## Contribution notes

- This is a fork. `origin` is the working fork; `upstream` is `github.com/kr8s-org/pytest-kind-ng`. Open PRs against
  `main`.
- Keep commit messages clean — **gitlint** runs as a pre-commit hook.
- Update tool version defaults (`KIND_VERSION` / `KUBECTL_VERSION`) and the README together when bumping supported
  Kubernetes/kind versions; the hard-coded `'1', '25'` assertions in `test_plugin.py` also need updating.
- Bump the CalVer `version` in `pyproject.toml` for releases.

## Git worktrees (required for agents)

**When an agent works on this repo, it must use a git worktree** rather than committing directly on a shared checkout.
This keeps parallel agent work isolated and avoids clobbering the primary working tree.

- Create worktrees inside the **`.worktrees/`** directory at the repo root. This directory is gitignored.
- Name each worktree after its branch/task.

Create a worktree for a new branch:

```bash
git worktree add .worktrees/my-task -b my-task
cd .worktrees/my-task
```

Or for an existing branch:

```bash
git worktree add .worktrees/my-task my-task
```

Work, commit, and push from inside the worktree. Each worktree is a full checkout, so install dependencies there as
needed (`poetry install`). Note that `.pytest-kind/` (downloaded binaries and cluster state) is per-checkout and
gitignored, so each worktree downloads its own binaries.

When finished, remove the worktree (and optionally the branch):

```bash
git worktree remove .worktrees/my-task
git branch -d my-task          # once merged
```

List and prune worktrees:

```bash
git worktree list
git worktree prune
```

Avoid running the cluster-creating tests from multiple worktrees at the same time with the **same** `--cluster-name`,
since kind cluster names are global to the Docker host — use distinct `--cluster-name` values (or run them serially) to
prevent collisions.
