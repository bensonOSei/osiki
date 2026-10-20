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

## Identifiers

Two kinds of id appear in the API:

- **External ids**, your own: users and tenants are addressed by them in `POST /authorization/check`, `POST /authorization/filter`, `/tenants/...` (including members) and `/users/by-external/{external_id}` (upsert and bundle).
- **Internal ids**, the ObjectIds Osiki returns as `id`: `/users/{id}`, `/users/{id}/roles`, `/users/{id}/groups`, `/groups/{id}`, `/groups/{id}/roles` and the role, permission, condition and constraint routes take these. The `id` field of any user response (create, get or upsert) is that internal id.

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

- `GET /snapshot` returns the environment's authorization configuration: `environment_id`, `version`, the active roles (each with its `parent_id` and its grants as `"resource:action"` strings plus an optional condition key), the conditions (key to rule), and the constraints. It has no separate permission or tenant lists, and no users: a user's tenants and assignments come from the bundle below. It carries an `ETag`; send it back as `If-None-Match` and an unchanged snapshot answers `304 Not Modified`. Responses are `Cache-Control: private` and `Vary: X-Osiki-Environment`.
- `GET /snapshot/version` returns just `{"version": n, "assignments_version": m}`, cheap to poll.
- `GET /users/by-external/{external_id}/bundle` returns one user's attributes, tenants and assignments.
- `POST /authorization/filter` takes `user_id`, `resource`, `action` and an optional `scope` and returns a list filter: `{"mode": "all"}`, `{"mode": "none"}`, or `{"mode": "filter", "filter": ...}` with a residual expression tree whose leaves carry a `type`. Use it to push the user's access rules into your own database query.

Every decision made locally must match the server's. The fixtures that pin this behaviour, and how an SDK loads them, are described in [conformance/README.md](conformance/README.md).

## Python SDK

[`osiki-sdk`](sdks/python/README.md) (import `osiki_sdk`) wraps a FastAPI app in `OsikiGuard`: every route is checked locally against the cached snapshot, and discovered routes are mapped to permissions with `PUT /endpoints/mapping`. It also translates rules into SQLAlchemy and Mongo list filters, syncs users and tenants, and sends decision logs in the background. Start with the dev-environment step in its README (`PUT /settings {"unmapped": "allow"}`), because every environment denies unmapped routes by default.

`tests/e2e/test_sdk_roundtrip.py` runs the SDK in-process against the real engine app (mock repositories): discovery, mapping, a record rule, revocation after one poll, a SQLAlchemy filter and decision-log ingest. Locally, `poetry install` installs the SDK as an editable path dependency (group `sdk`) with its `sqlalchemy` extra; it needs the `sdks/` directory, which a checkout has.

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

## Team management for your customers

Osiki can let a business that uses your product manage its own staff: create roles, add members, assign and revoke roles. Your product's dashboard calls the tenant team API at `/api/v1/tenants/{tenant_id}/team`, and the engine enforces what that business may do.

### Who is acting: `X-Osiki-Actor`

Osiki has no login of its own. Your own front door authenticates the person and tells the engine who it is with the `X-Osiki-Actor` header, either `developer:<id>` or `tenant_user:<id>` (the id is 1 to 128 characters of `A-Z a-z 0-9 . _ @ -`). A `tenant_user` id is the engine's external user id.

> **Never expose the engine without a front door that sets `X-Osiki-Actor`.** The engine trusts the header. A missing header means `developer:anonymous`, and a developer passes the team-manager and no-escalation checks (they still get `not_assignable`, `not_offered`, `constraint` and `last_manager`). A malformed header returns `422`.
>
> No engine route has authentication, and every developer route ignores `X-Osiki-Actor`. That includes `/roles`, `/users/{id}/roles`, `/permissions`, `/constraints`, `/tenants/...` (outside `/team`) and `PUT /environment/bootstrap`. Your front door must expose **only** `/api/v1/tenants/{their tenant}/team/...` to tenant users, pin `X-Osiki-Environment` itself, and set `X-Osiki-Actor` itself (strip any value a client sends). Everything else is developer-only.

The actor is recorded on every team change in the audit log (`GET /tenants/{tenant_id}/team/audit-logs`).

### Setting it up

1. **Bootstrap.** `PUT /api/v1/environment/bootstrap` creates the built-in permission `osiki.team:manage` and the `Owner` template if they are missing. It is safe to repeat (the Owner template cannot be deleted, so it always finds it), and returns `team_manage_permission_id` and `owner_role_id`. It answers `409` if another role already uses the name `Owner`.
2. **Mark what a business may hand out.** Set `assignable: true` on each permission via `PATCH /permissions/{id}`. Tenant roles can hold only assignable permissions.
3. **Owner setup (M3A-29).** The seeded `Owner` template grants only `osiki.team:manage`, and a team manager can hand out only what they hold. So you must add the business's assignable permissions to the Owner template. It is editable except for renaming it, changing `is_template`, or dropping `osiki.team:manage` (each is a `422`).
4. **Give a business its first manager.** Add the first member with the `Owner` role as a developer actor (`POST /tenants/{tenant_id}/team/members`). From then on a manager can add the rest of their team.
5. **Offer templates.** A template (a project role with `is_template: true`) is offered to a tenant when every permission it grants, including its parents', is assignable or built-in. A manager can assign an offered template, or start a tenant role from one: `copied_from` records provenance only, so send the grants in the request body too.

### What a team manager can do

A `tenant_user` who holds `osiki.team:manage` in the tenant can, for that tenant only:

| Call | Does |
|---|---|
| `GET /roles`, `POST /roles`, `PATCH /roles/{id}`, `DELETE /roles/{id}` | List offered templates and the tenant's own roles; create, rename, regrant and delete tenant roles |
| `GET /members`, `POST /members` | List members (paged); add a member with a role |
| `PUT /members/{user_id}/roles/{role_id}`, `DELETE ...` | Assign or revoke a role |
| `DELETE /members/{user_id}` | Remove a member and every role they hold in the tenant |
| `GET /members/{user_id}/effective` | The grants the member holds and which role gives each |
| `POST /validate` | Dry run: the rules the operation would break (`op` plus `args`); writes nothing |
| `GET /permissions` | The permissions a tenant role may hold, for a role editor |

**No escalation.** A manager can only grant permissions they hold themselves. A tenant role may not hold built-in `osiki.*` permissions, and tenant roles cannot contain resource-wildcard (`*:...`) permissions (M3A-10), because such a wildcard would match `osiki.team:manage`.

### Contracts your front door must keep

- **add_member (M3A-19).** `user_id` must identify a user who consented or authenticated, such as one who accepted an invite. The engine returns that user's environment-wide name and email to the tenant's managers.
- **Tenant users and 403 (M3A-28).** A `tenant_user` gets `403` for a tenant they do not manage, even one that does not exist, so they cannot probe which tenants exist.
- **Exact bodies (M3A-30).** Team request bodies reject unknown fields (`422`).
- **Last-manager guard (M3A-21).** A tenant must keep at least one member holding `osiki.team:manage`. The guard binds team operations only. Developer routes (such as `DELETE /tenants/{id}/members/{user_id}` and `DELETE /users/{id}/roles/{role_id}`) can still remove the last manager.
- **Constraint targets (M3A-25).** Constraints target project roles and templates; a tenant-role id gets `422`. A tenant's copies of a template are bound through their template.
- **Global cardinality (M3A-27).** A `GLOBAL` cardinality constraint on a template counts assignments of the template and of its copies across tenants, and is not serialized across tenants, so concurrent assignments in different tenants can overshoot it.

### Errors

Team conflicts are `409` with a machine-readable `details.reason`:

| `details.reason` | Meaning |
|---|---|
| `last_manager` | The change would leave the tenant with no manager |
| `escalation` | The role holds permissions the actor does not (`details.uncovered` lists them) |
| `not_assignable` | A permission cannot be given to a tenant role (`details.permissions` lists them) |
| `role_in_use` | A role to delete is still assigned |
| `not_offered` | The template is not offered to this tenant |
| `constraint` | A constraint refused the assignment (`details.constraint`, `details.detail`) |

Some team `409`s carry no `details.reason`: the duplicates (a role name already taken, a role already assigned, an email already in use).

Other statuses: `403` (the actor does not manage the tenant, `details.reason: not_manager`), `404` and `422`. Under transaction contention the engine retries, then answers `503` with `error: "busy"` and a `Retry-After` header; the call may be retried.

### Transactions (M3A-20)

Each team write runs in one MongoDB transaction. Set `MONGODB_TRANSACTIONS=true` (default `false`) and run MongoDB as a replica set; standalone MongoDB rejects transactions. **The last-manager guard is race-safe only when `MONGODB_TRANSACTIONS=true` on a replica set.** The dev `docker-compose.yml` runs a single-node replica set (`rs0`) and `.env.example` turns the setting on. To run the API on the host against it, use `MONGODB_URL=mongodb://localhost:27017/osiki?directConnection=true`.

### Upgrading to v0.3.0

Run `scripts/migrate_m3.py` before the new version takes traffic, and never run old and new versions side by side. It drops the old unique role-name index `(environment_id, name)`, which would otherwise reject a tenant role that shares a name with a project role, and then lets Beanie create the new `(environment_id, tenant_id, name)` index. It reads `MONGODB_URL` and `MONGODB_DATABASE` (or `--mongodb-url` and `--database`) and is safe to run repeatedly. No documents change.

```bash
poetry run python scripts/migrate_m3.py
```

## Key concepts

- **Permissions** are `resource:action` pairs (e.g. `invoices:write`, `reports:read`). Wildcards work too — `invoices:*`, `*:read`, `*:*`. Neither part may be empty or contain `:`.
- **Roles** hold collections of permissions and can inherit from parent roles. A role chain like `viewer → editor → admin` means admins get everything editors and viewers have.
- **Groups** let you assign roles to many users at once. Add a user to the "finance-team" group and they get all roles attached to that group.
- **Scopes** handle multi-tenancy. A role can be scoped to `{ "tenant_id": "acme-corp", "region": "eu" }` so permissions only apply within that context. Scope values are strings; custom keys are allowed, but a non-string value is rejected with `422`.
- **Constraints** enforce business rules — mutual exclusion between roles, cardinality limits, and prerequisite requirements.
- **Access logs** record authorization checks (all denials, sampled successes). Changes made through the tenant team API are written to the audit log (actor, action, before and after); changes through the developer routes are not audited in this version.

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

`MONGODB_TRANSACTIONS=true` requires MongoDB to run as a replica set. If you run the server on the host against the compose MongoDB replica set, add `?directConnection=true` to `MONGODB_URL` (for example `mongodb://localhost:27017/osiki?directConnection=true`), because the replica set advertises its member as `mongodb:27017`, which the host cannot resolve.

Then start the dev server:

```bash
make dev
```

The server runs on `http://localhost:8000` with hot reload enabled.

## API overview

All endpoints live under `/api/v1`. Here's the shape of things:

| Resource | Endpoints |
|---|---|
| **Users** | Create, get, update, delete, list. Assign/revoke roles (`?tenant_id=` on revoke). Add/remove from groups. Upsert and bundle by external id. |
| **Groups** | Create, get, update, delete, list. Assign/revoke roles (`?tenant_id=` on revoke). |
| **Roles** | Create, get, update, delete, list. |
| **Permissions** | Create, get, update, delete, list. |
| **Conditions** | Create, get, update, delete, list. |
| **Constraints** | Create, get, update, delete, list. |
| **Tenants** | Upsert, get. Add/remove/list members. |
| **Authorization** | `POST /authorization/check` — the main event. `POST /authorization/filter` for list filters. |
| **Snapshot** | `GET /snapshot` (ETag/304), `GET /snapshot/version`, `GET /users/by-external/{id}/bundle`. |
| **Environment** | `PUT /environment/bootstrap`: create the `osiki.*` built-ins and the Owner template. |
| **Team** | `/tenants/{id}/team/...`: roles, members, validate, permissions and audit logs for a tenant's own managers (see Team management). |
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
