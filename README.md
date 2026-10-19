# Osiki

A role-based access control (RBAC) service built with FastAPI and MongoDB. Osiki handles the "who can do what" part of your application so you don't have to build it from scratch every time.

It supports hierarchical roles, multi-tenant scoping, group-based assignments, and business rule constraints — all behind a single authorization check endpoint.

## What it does

You send a request like "can user X perform action Y on resource Z?" and Osiki figures out the answer by resolving permissions through direct role assignments, group memberships, and role inheritance chains. It also enforces constraints like mutual exclusion (a user can't be both payment initiator and approver) and prerequisite roles.

**Core authorization check:**

`user_id` is your application's own (external) user id. `record` is optional: send the record being accessed when a grant carries a condition.

```bash
curl -X POST http://localhost:8000/api/v1/authorization/check \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "abc-123",
    "resource": "invoices",
    "action": "write",
    "scope": { "tenant_id": "acme-corp" },
    "record": { "team_id": "t-7" }
  }'
```

```json
{
  "allowed": true,
  "matched_permission": "invoices:write",
  "matched_via": "direct",
  "condition": "own_team",
  "denial_reason": null,
  "cache_hit": false
}
```

`condition` is the key of the named condition that allowed the request, or `null` for an unconditional grant.

## Environments

Every request is scoped to an environment. Send it in the `X-Osiki-Environment` header; when the header is missing the environment is `default`. Environments are fully isolated: users, roles, conditions, tenants and logs in one are invisible to the others. Identifiers are lowercase letters, digits, `-` and `_`.

```bash
curl http://localhost:8000/api/v1/roles -H "X-Osiki-Environment: staging"
```

## Tenants and membership

Tenants are identified by your own external id. Upsert one, then add users (by external id) to it. A user who is not a member of a tenant is denied inside that tenant's scope.

```bash
curl -X PUT http://localhost:8000/api/v1/tenants/acme-corp \
  -H "Content-Type: application/json" -d '{"name": "Acme Corp"}'

curl -X PUT http://localhost:8000/api/v1/users/by-external/abc-123 \
  -H "Content-Type: application/json" -d '{"name": "Ama", "attributes": {"team_id": "t-7"}}'

curl -X PUT http://localhost:8000/api/v1/tenants/acme-corp/members/abc-123
```

Remove a member with `DELETE` on the same path; `GET /tenants/{id}/members` lists them.

Membership comes first. Assigning a user a role scoped to a tenant does not make them a member: if they are not one already, the assignment is rejected with `409 Conflict` (`"User is not a member of this tenant"`, with a `hint` to add the membership first). An unknown tenant answers `404`.

To revoke a tenant-scoped assignment, name the tenant: `DELETE /users/{id}/roles/{role_id}?tenant_id=acme-corp` (and the same on `/groups/{id}/roles/{role_id}`). Without `tenant_id`, only the project-wide assignment of that role is revoked; if there is none the answer is `404`, never a guess at one of the tenants.

## Conditions

A condition is a named rule, written as a JSON expression tree, that a role grant can carry. It is evaluated against the `record` sent with the check, and against the user's attributes. This one allows access when the record belongs to the user's team:

```bash
curl -X POST http://localhost:8000/api/v1/conditions \
  -H "Content-Type: application/json" \
  -d '{
    "key": "own_team",
    "name": "Own team",
    "expression": {
      "op": "eq",
      "left": { "ref": "record.team_id" },
      "right": { "ref": "user.team_id" }
    }
  }'
```

Then grant a permission through that condition when you create the role:

```bash
curl -X POST http://localhost:8000/api/v1/roles \
  -H "Content-Type: application/json" \
  -d '{
    "name": "team-member",
    "grants": [{ "permission_id": "<permission id>", "condition_id": "<condition id>" }]
  }'
```

Without a `record`, a conditional grant does not allow. When in doubt, Osiki denies.

## Snapshot, bundle and filter

These endpoints let an SDK decide locally instead of calling `/authorization/check` for every request.

- `GET /snapshot` returns the environment's whole configuration (permissions, roles, conditions, constraints, tenants). It carries an `ETag`; send it back as `If-None-Match` and an unchanged snapshot answers `304 Not Modified`.
- `GET /snapshot/version` returns just `{"version": n}`, cheap to poll.
- `GET /users/by-external/{external_id}/bundle` returns one user's attributes, tenants and assignments.
- `POST /authorization/filter` takes `user_id`, `resource`, `action` and an optional `scope` and returns a list filter: `{"mode": "all"}`, `{"mode": "none"}`, or `{"mode": "filter", "filter": ...}` with a residual expression tree whose leaves carry a `type`. Use it to push the user's access rules into your own database query.

Every decision made locally must match the server's. The fixtures that pin this behaviour, and how an SDK loads them, are described in [conformance/README.md](conformance/README.md).

## Constraints

Constraints are enforced when roles are assigned: directly to a user, to a group, or by adding a user to a group. A violating assignment is rejected with `409 Conflict`, naming the constraint and the reason.

Constraints respect tenant scope. A prerequisite counts only when it is held project-wide or in the same tenant as the new assignment (a project-wide assignment needs a project-wide prerequisite). Mutually exclusive roles may be held in two different tenants, but not in the same tenant, and not when either of them is project-wide.

## Access logs

The server records every denial and a sample of successful checks (`ACCESS_LOG_SUCCESS_SAMPLE_RATE`, default `0.1`). Writing happens after the response is sent, so logging never slows or changes a check. SDKs that decide locally report their decisions in batches:

```bash
curl -X POST http://localhost:8000/api/v1/access-logs/batch \
  -H "Content-Type: application/json" \
  -d '{ "entries": [{
    "timestamp": 1760000000.5, "user_id": "abc-123", "resource": "invoices",
    "action": "write", "scope": { "tenant_id": "acme-corp" },
    "allowed": true, "matched_permission": "invoices:write", "latency_ms": 0.2
  }] }'
```

Send 1 to 500 entries; the response is `202 {"accepted": n}`. They are stored with `source: "sdk"`.

## Upgrading existing data

If you are upgrading a deployment that already has data:

1. Stop every instance of the old version. Old and new versions must never run side by side against the same database: the old one writes documents without an environment and with the old role format.
2. Run `scripts/migrate_m1.py`.
3. Start the new version, and only then send it traffic.

```bash
poetry run python scripts/migrate_m1.py
```

The migration stamps every existing document with the `default` environment, converts each role's `permission_ids` into unconditional `grants` (merged into any grants the role already has, so no permission is lost), and drops the indexes the new version no longer uses, including the old unique ones that would otherwise keep rejecting valid writes. It reads `MONGODB_URL` and `MONGODB_DATABASE` from the environment and is safe to run repeatedly.

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
| **Conditions** | Create, get, update, delete, list. |
| **Constraints** | Create, get, update, delete, list. |
| **Tenants** | Upsert, get. Add/remove/list members. |
| **Authorization** | `POST /authorization/check` — the main event. `POST /authorization/filter` for list filters. |
| **Snapshot** | `GET /snapshot` (ETag/304), `GET /snapshot/version`, `GET /users/by-external/{id}/bundle`. |
| **Access logs** | `POST /access-logs/batch` — SDK decision ingest. |

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
