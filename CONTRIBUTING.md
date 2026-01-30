# Contributing to Osiki

Thanks for considering a contribution. This guide covers everything you need to go from cloning the repo to opening a pull request.

## Getting set up

### The quick way

```bash
./scripts/setup.sh
```

This checks your prerequisites (Python 3.13, Poetry, Docker), installs dependencies, sets up pre-commit hooks, and offers to start the Docker services. It can also add an `osiki` shell alias for the CLI.

### The manual way

```bash
poetry install
poetry run pre-commit install
```

You'll need Docker running for MongoDB and Redis:

```bash
make up
```

Verify things are working:

```bash
make test
```

## Making changes

### Branch naming

Use descriptive branch names. No strict convention, but something like `fix/scope-matching-edge-case` or `feat/add-bulk-role-assignment` keeps things clear.

### Where to put things

Osiki follows a layered architecture. Each layer has one job:

```
routes → services → repositories → models
```

- **Models** (`osiki/models/`) — MongoDB document definitions using Beanie. Inherit from the base mixins in `base.py` for timestamps, soft deletes, and metadata.
- **Schemas** (`osiki/schemas/`) — Pydantic models for request/response validation. These are separate from database models on purpose.
- **Repositories** (`osiki/repositories/`) — Data access. Each entity has an abstract base class and a MongoDB implementation. Tests mock at this layer.
- **Services** (`osiki/services/`) — Business logic. Services depend on repositories via dependency injection, never on the database directly.
- **Routes** (`osiki/api/routes/`) — Thin HTTP handlers. Validate input, call a service, return the response. Keep logic out of here.

Dependencies flow downward only. Routes never import models directly, services never talk to the database directly.

### Adding a new entity

The CLI can scaffold everything for you:

```bash
poetry run osiki generate all Invoice --fields "amount:float status:str"
```

This creates a model, repository (abstract + MongoDB implementation), service, and route. You can also generate pieces individually:

```bash
poetry run osiki generate model Invoice --fields "amount:float"
poetry run osiki generate repository Invoice
poetry run osiki generate service Invoice
poetry run osiki generate route invoice
```

After generating, you'll need to:
1. Register the model in `osiki/configs/database.py`
2. Wire up the repository and service in `osiki/api/dependencies.py`
3. Include the router in `osiki/main.py`

### Writing tests

Tests live in `tests/` and are split into three categories:

- **`tests/unit/`** — Test service logic in isolation using mock repositories from `tests/mocks/`.
- **`tests/integration/`** — Test repository implementations against `mongomock-motor` (no real database needed).
- **`tests/e2e/`** — Test full API workflows through FastAPI's test client with `httpx`.

All tests run async by default (`asyncio_mode = "auto"` in pyproject.toml). Fixtures are in `tests/conftest.py`.

A few ground rules:

- New features need tests. Bug fixes should include a test that would have caught the bug.
- Coverage target is 100%. Run `make test-cov` to check. The coverage config omits `main.py`, `configs/`, and the health route since those are infrastructure.
- Tests shouldn't depend on a running database. Use `mongomock-motor` for integration tests and mock repositories for unit tests.

## Code style

Pre-commit hooks handle this automatically on every commit. The chain is:

1. **Black** — formatting (88 char line length)
2. **Ruff** — linting (E, F, I, N, W, UP rule sets)
3. **MyPy** — type checking in strict mode

To run them manually:

```bash
make format     # black + ruff --fix
make lint       # ruff check
make typecheck  # mypy
make pre-commit # all of the above
```

A few things to keep in mind:

- Type hints are required everywhere (MyPy strict mode). If you're adding a new function, annotate it fully.
- Ruff ignores `E712` because Beanie's query syntax requires `== True` / `== False` comparisons.
- MyPy excludes the `tests/` directory.

## Running the project

```bash
make dev    # start the dev server (hot reload on localhost:8000)
make up     # start MongoDB + Redis + API via Docker
make down   # stop Docker services
make logs   # tail Docker logs
make shell  # shell into the API container
```

The full list of commands is in `make help`.

## Submitting a pull request

1. Make sure tests pass: `make test`
2. Make sure the code is clean: `make pre-commit`
3. Write a clear PR description — what changed and why.
4. If you're adding a new feature, mention it in the PR so the README can be updated.

That's it. If something in this guide is unclear or out of date, feel free to open an issue about it.
