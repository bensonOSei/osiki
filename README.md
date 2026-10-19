# Osiki

A role-based access control (RBAC) service built with FastAPI and MongoDB. Osiki handles the "who can do what" part of your application so you don't have to build it from scratch every time.

It supports hierarchical roles, multi-tenant scoping, group-based assignments, and business rule constraints — all behind a single authorization check endpoint.

## What it does

You send a request like "can user X perform action Y on resource Z?" and Osiki figures out the answer by resolving permissions through direct role assignments, group memberships, and role inheritance chains. It also enforces constraints like mutual exclusion (a user can't be both payment initiator and approver) and prerequisite roles.

**Core authorization check:**

```bash
curl -X POST http://localhost:8000/api/v1/authorization/check \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "abc-123",
    "resource": "invoices",
    "action": "write",
    "scope": { "tenant_id": "acme-corp" }
  }'
```

```json
{
  "allowed": true,
  "matched_permission": "invoices:write",
  "matched_via": "direct",
  "condition": null,
  "denial_reason": null,
  "cache_hit": false
}
```

## Key concepts

- **Permissions** are `resource:action` pairs (e.g. `invoices:write`, `reports:read`). Wildcards work too — `invoices:*`, `*:read`, `*:*`.
- **Roles** hold collections of permissions and can inherit from parent roles. A role chain like `viewer → editor → admin` means admins get everything editors and viewers have.
- **Groups** let you assign roles to many users at once. Add a user to the "finance-team" group and they get all roles attached to that group.
- **Scopes** handle multi-tenancy. A role can be scoped to `{ "tenant_id": "acme-corp", "region": "eu" }` so permissions only apply within that context.
- **Constraints** enforce business rules — mutual exclusion between roles, cardinality limits, and prerequisite requirements.
- **Audit logs** track every administrative change. **Access logs** record authorization checks (all denials, sampled successes).

## Getting started

**Prerequisites:** Python 3.13+, [Poetry](https://python-poetry.org/), Docker & Docker Compose

### With Docker (recommended)

```bash
git clone <repo-url> && cd osiki
make up
```

This starts MongoDB, Redis, and the API server. The API is available at `http://localhost:8000`. Check `http://localhost:8000/health` to verify everything is running.

### Local development

If you prefer running the server directly:

```bash
poetry install
```

You'll need MongoDB and Redis running locally. Update `.env` if your connection URLs differ from the defaults:

```
MONGODB_URL=mongodb://localhost:27017/osiki
MONGODB_DATABASE=osiki
REDIS_URL=redis://localhost:6379
REDIS_PASSWORD=
```

Then start the dev server:

```bash
make dev
```

The server runs on `http://localhost:8000` with hot reload enabled.

## API overview

All endpoints live under `/api/v1`. Here's the shape of things:

| Resource | Endpoints |
|---|---|
| **Users** | Create, get, update, delete, list. Assign/revoke roles. Add/remove from groups. |
| **Groups** | Create, get, update, delete, list. Assign/revoke roles. |
| **Roles** | Create, get, update, delete, list. |
| **Permissions** | Create, get, list. |
| **Authorization** | `POST /authorization/check` — the main event. |

Once the server is running, full interactive docs are at `http://localhost:8000/docs`.

## Project structure

```
osiki/
├── osiki/                  # The application
│   ├── main.py             # FastAPI app setup
│   ├── api/
│   │   ├── routes/         # Endpoint handlers
│   │   ├── dependencies.py # Dependency injection
│   │   ├── exceptions.py   # Error handling
│   │   └── middleware/      # Request ID tracking
│   ├── models/             # MongoDB document models (Beanie ODM)
│   ├── schemas/            # Request/response Pydantic models
│   ├── repositories/       # Data access layer
│   ├── services/           # Business logic
│   │   ├── authorization/        # The main authorization check (via decide)
│   │   ├── snapshot_builder/     # Versioned, cached config snapshot
│   │   ├── bundle_builder/       # One user's attributes, tenants, assignments
│   │   └── constraint_validator/ # Enforces business rules
│   └── configs/            # Settings, database init, logging
├── cli/                    # Code generation CLI (Typer)
├── tests/                  # Unit, integration, and e2e tests
└── docs/                   # Schema design documentation
```

The architecture follows a layered pattern: **routes → services → repositories → models**. Each layer has a clear job and dependencies only flow downward.

## Contributing

### Setup

The quickest way to get everything ready is the setup script. It checks that you have the right Python, Poetry, and Docker versions, installs dependencies, wires up pre-commit hooks, and optionally starts the Docker services:

```bash
./scripts/setup.sh
```

It'll also offer to add an `osiki` alias to your shell so you can run CLI commands directly.

If you'd rather do things manually:

```bash
poetry install
poetry run pre-commit install
```

### Running tests

```bash
make test              # all tests
make test-unit         # unit tests only
make test-integration  # integration tests only
make test-cov          # with coverage report
```

Tests use `mongomock-motor` so you don't need a running MongoDB instance. The test suite has 143+ tests targeting 100% coverage.

### Code quality

Pre-commit hooks run Black (formatting), Ruff (linting), and MyPy (type checking) automatically on commit. You can also run them manually:

```bash
make format     # black + ruff --fix
make lint       # ruff check
make typecheck  # mypy (strict mode)
make pre-commit # all hooks at once
```

### Code generation

Osiki has a CLI that scaffolds new entities:

```bash
# generate a full stack (model, repository, service, route)
poetry run osiki generate all Invoice --fields "amount:float status:str"

# or generate individual pieces
poetry run osiki generate model Invoice --fields "amount:float"
poetry run osiki generate repository Invoice
poetry run osiki generate service Invoice
poetry run osiki generate route invoice
```

### How things fit together

If you're adding a new feature or fixing a bug, here's the flow:

1. **Models** (`osiki/models/`) define the MongoDB document structure using Beanie. They inherit from base mixins that handle timestamps, soft deletes, and metadata.
2. **Repositories** (`osiki/repositories/`) handle all database operations. Each entity has an abstract base and a MongoDB implementation. This makes testing easy — tests swap in mock repositories.
3. **Services** (`osiki/services/`) contain business logic. They depend on repositories (injected via FastAPI's `Depends`), never on the database directly.
4. **Routes** (`osiki/api/routes/`) are thin — they validate input, call a service, and return the response.
5. **Schemas** (`osiki/schemas/`) define the request and response shapes, separate from database models.

For a deeper look at the data model, permission resolution algorithm, and caching strategy, see [docs/schema_design.md](docs/schema_design.md). For the full contributing guide (branch naming, where to put things, writing tests, PR workflow), see [CONTRIBUTING.md](CONTRIBUTING.md).

## Tech stack

- **FastAPI** + **Uvicorn** — async web framework
- **MongoDB** (via **Beanie** ODM) — document store
- **Redis** — caching layer
- **Typer** + **Jinja2** — CLI and code generation
- **Pytest** + **mongomock-motor** — testing without a real database
- **Black** + **Ruff** + **MyPy** — code quality (strict mode)

## License

Apache 2.0 — see [LICENSE](LICENSE) for the full text.
