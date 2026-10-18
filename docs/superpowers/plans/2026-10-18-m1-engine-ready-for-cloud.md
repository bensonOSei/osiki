# M1 — Engine Ready for the Cloud: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the open-source Osiki engine into something the cloud and the SDKs can sit on. That means records namespaced by environment, real tenants with strict isolation, role grants that can carry record-level conditions, one pure decision function shared by the server and (later) the SDKs, a versioned snapshot export, constraints enforced on assignment, and access logging moved off the request path.

**Architecture:** Every document gains an `environment_id` string, taken from an `X-Osiki-Environment` header (default `"default"`). Repositories are built per request and bound to that environment. Record rules are stored as a JSON AST, never a string DSL, so SDKs only have to evaluate JSON. A new pure package, `osiki/decision/`, holds the rule evaluator, the residual-filter compiler and `decide()`. The server builds a `Snapshot` (cached by config version) plus a per-user `UserBundle` and calls `decide()`, the same function the M2 SDK will run locally. JSON conformance fixtures pin the behaviour so every future SDK can be checked against it.

**Tech Stack:** Python 3.13, FastAPI 0.128, Beanie 2 / PyMongo async, Pydantic 2, pytest + pytest-asyncio + mongomock-motor, Poetry.

**Spec:** `docs/superpowers/specs/2026-10-18-osiki-cloud-design.md` (§4, §5.4, §5.5, §6, §7, §8 M1)

## Global Constraints

- Python `>=3.13,<3.14`; mypy `strict = true` with `plugins = ["pydantic.mypy"]`; ruff rules `E F I N W UP`; black line length 88.
- Coverage `fail_under = 100`. Every task must leave `poetry run pytest --cov=osiki` at 100%.
- `asyncio_mode = "auto"`: async tests need no marker.
- Every new or changed `Base*Repository` method gets a matching method on its `Mock*Repository` in `tests/mocks/repositories.py`. Every new model gets a `make_*` factory in `tests/mocks/factories.py`, re-exported from `tests/mocks/__init__.py` and `tests/conftest.py`.
- Follow the existing layering: `models/` → `repositories/<name>/{base_*,mongodb_*}.py` → `services/<name>/{base_*,*}.py` → `api/routes/*.py`, wired in `api/dependencies.py`.
- Tenant isolation is non-negotiable (spec §2): when in doubt, deny.
- Out of scope for M1 (spec §7/§9): organizations, projects, API-key management, billing, endpoint mappings, push transport for change events, tenant roles and customer-assignable flags (M3). Redis stays in compose but gets no code: the snapshot replaces it.
- One PR for all of M1 (the owner's standing rule). Phases A/B/C are checkpoints where the suite is green, not separate PRs.

## Review Focus

1. **A user who isn't a member of the tenant asks about it** while holding a project-wide (unscoped) assignment. Expect a deny with `not_tenant_member`. Pinned in Task A3.
2. **The same `external_id`, role name or group name in two environments.** Expect both to be creatable, with nothing in env `a` ever visible to or granting in env `b`. Pinned in Task A1.
3. **A rule that references a missing record field or a user attribute that was never synced, including under `not`.** Expect a deny, never an error or an allow. Pinned in Task B1.
4. **A conditional grant on a wildcard** (`invoices:*` with "own team") checked against `invoices:delete`. Expect the condition to apply, and a missing record to give `record_required`. Pinned in Task B4.
5. **The snapshot `version` after role deactivation, grant removal, or a condition or constraint edit**, not only after creates. Expect it to increase on every config write. Pinned in Task B5.

---

## File Structure

```
osiki/
  api/
    environment.py                 NEW  X-Osiki-Environment header dependency
    dependencies.py                MOD  env-bound repo factories, new services
    routes/
      tenants.py                   NEW  tenant upsert/get, membership
      conditions.py                NEW  named-condition CRUD
      snapshot.py                  NEW  GET /snapshot, /snapshot/version
      access_logs.py               NEW  POST /access-logs/batch
      users.py                     MOD  PUT /users/by-external/{id}, bundle, constraint check
      groups.py                    MOD  constraint check on group-role + membership
      roles.py                     MOD  grants, same-env parent validation
      permissions.py               MOD  /effective uses decide.effective_grants
      authorization.py             MOD  external user id, record, /filter, async logging
  models/
    base.py                        MOD  EnvironmentMixin, AttributeValue
    tenant.py, tenant_member.py    NEW
    condition.py                   NEW
    environment_state.py           NEW  config_version counter
    role.py                        MOD  grants replace permission_ids
    user.py                        MOD  name, attributes
    access_log.py                  MOD  environment_id, tenant_id, source
    (all other documents)          MOD  EnvironmentMixin + compound indexes
  repositories/
    tenants/, tenant_members/, conditions/, environment_state/   NEW
    (all existing)                 MOD  __init__(environment_id), env filter
  decision/                        NEW  pure: no I/O, no Beanie imports
    __init__.py
    rules.py                       rule AST models, validate, evaluate, residualize
    models.py                      Snapshot, UserBundle, DecisionRequest, Decision, ...
    scope.py                       scope_matches (moved from ScopeMatcher)
    decide.py                      decide, effective_grants, list_filter
  services/
    snapshot_builder/              NEW  Snapshot from repos, cached by version
    bundle_builder/                NEW  UserBundle from repos
    authorization/                 MOD  delegates to decide()
    permission_resolver/           DEL  replaced by bundle_builder + decide
    scope_matcher/                 MOD  delegates to decision.scope
conformance/
  README.md                        NEW  fixture format for SDK authors
  decisions/*.json                 NEW
  filters/*.json                   NEW
scripts/
  migrate_m1.py                    NEW  stamp environment_id, permission_ids→grants, drop old indexes
tests/conformance/test_conformance.py  NEW
```

---

## Phase A — Environments and tenancy

### Task A1: Environment namespacing

**Files:**
- Create: `osiki/api/environment.py`, `scripts/migrate_m1.py`, `tests/e2e/test_environments.py`, `tests/integration/repositories/test_environment_isolation.py`
- Modify: `osiki/models/base.py`, every document in `osiki/models/`, every `osiki/repositories/*/mongodb_*.py`, `osiki/api/dependencies.py`, `tests/mocks/repositories.py`, `tests/conftest.py`, `tests/e2e/conftest.py`

**Interfaces:**
- Produces:
  - `osiki.models.base.EnvironmentMixin`: a pydantic mixin with `environment_id: str = "default"`.
  - `osiki.api.environment.ENVIRONMENT_HEADER = "X-Osiki-Environment"` and `DEFAULT_ENVIRONMENT = "default"`.
  - `def get_environment_id(x_osiki_environment: Annotated[str | None, Header()] = None) -> str` and `EnvironmentId = Annotated[str, Depends(get_environment_id)]`.
  - Every `MongoDB*Repository` and `Mock*Repository` takes `__init__(self, environment_id: str)` and exposes `self.environment_id`.

- [ ] **Step 1: Write failing tests.**
  - `tests/e2e/test_environments.py`:
    - `test_missing_header_uses_default_environment`: create a role with no header, then list it with `X-Osiki-Environment: default`. It appears.
    - `test_invalid_environment_header_rejected`: header `"Bad Env!"` → 422.
    - `test_role_in_env_a_invisible_in_env_b`: create role `"editor"` with header `a`; `GET /roles` with header `b` returns `items == []`.
    - `test_same_role_name_allowed_in_two_envs`: `POST /roles {"name":"editor"}` under `a` and under `b` both return 201.
  - `tests/integration/repositories/test_environment_isolation.py` (mongomock):
    - `test_same_external_id_in_two_envs`: `MongoDBUserRepository("a").create(User(external_id="u1"))` and the same in `"b"` both succeed. `MongoDBUserRepository("b").get_by_external_id("u1").environment_id == "b"`.
    - `test_get_by_id_does_not_cross_envs`: a role created in `"a"` → `MongoDBRoleRepository("b").get_by_id(str(role.id)) is None`.
- [ ] **Step 2: Run them.** `poetry run pytest tests/e2e/test_environments.py tests/integration/repositories/test_environment_isolation.py -v` → FAIL.
- [ ] **Step 3: Models.** Add `EnvironmentMixin` to all ten documents. Replace `Indexed(str, unique=True)` with plain fields plus compound unique `IndexModel`s in `Settings.indexes`:
  - User: `(environment_id, external_id)`; `(environment_id, email)` unique with `partialFilterExpression={"email": {"$type": "string"}}`.
  - Role: `(environment_id, name)`. Group: `(environment_id, name)`.
  - Permission: `(environment_id, resource, action)`.
  - UserRole, GroupRole, UserGroup: prefix their existing unique index with `environment_id`.
  - Add `("environment_id", 1)` as the leading key of every existing non-unique query index.
- [ ] **Step 4: `get_environment_id`.** Absent header → `"default"`. The value must match `^[a-z0-9][a-z0-9_-]{0,62}$`, otherwise raise the existing `ValidationError` (422).
- [ ] **Step 5: Repositories.** Each Mongo repo stores `environment_id`. Every `find`/`find_one`/`get` adds `environment_id == self.environment_id`; `get(id)` becomes `find_one({"_id": oid, "environment_id": ...})`. `create` stamps `environment_id` before insert. Mirror this in the mocks: they filter on `environment_id` and stamp it on create.
- [ ] **Step 6: Dependencies.** Every `get_*_repository` takes `environment_id: EnvironmentId` and returns `MongoDB*Repository(environment_id)`. Update `tests/e2e/conftest.py` overrides to return mock repos keyed by environment from a module-level `dict[str, Mock*Repository]`, so env isolation is real in e2e.
- [ ] **Step 7: Migration script.** `scripts/migrate_m1.py` (run with `poetry run python scripts/migrate_m1.py`; reads `MONGODB_URL`/`MONGODB_DATABASE`). It is idempotent:
  - `update_many({"environment_id": {"$exists": False}}, {"$set": {"environment_id": "default"}})` on all ten collections.
  - Drop the indexes `name_1` (roles, groups), `external_id_1` and `email_1` (users), and `resource_1_action_1` (permissions) when they exist.
  - Print a count per collection.
  - Task B3 extends it.
- [ ] **Step 8: Run the full suite.** `poetry run pytest --cov=osiki` → all pass at 100%. Fix existing tests that construct repos with no argument by passing `"default"`.
- [ ] **Step 9: Commit.** `git commit -m "feat: namespace all engine records by environment"`

### Task A2: Tenants, membership, and user upsert

**Files:**
- Create: `osiki/models/tenant.py`, `osiki/models/tenant_member.py`, `osiki/repositories/tenants/{__init__,base_tenant_repository,mongodb_tenant_repository}.py`, `osiki/repositories/tenant_members/{__init__,base_tenant_member_repository,mongodb_tenant_member_repository}.py`, `osiki/schemas/tenant.py`, `osiki/api/routes/tenants.py`, `tests/e2e/test_tenants.py`, `tests/integration/repositories/test_tenant_repository.py`, `tests/integration/repositories/test_tenant_member_repository.py`
- Modify: `osiki/models/base.py`, `osiki/models/user.py`, `osiki/schemas/user.py`, `osiki/api/routes/users.py`, `osiki/api/routes/__init__.py`, `osiki/main.py`, `osiki/configs/database.py`, `tests/conftest.py` (register new docs with `init_beanie`)

**Interfaces:**
- Consumes: `EnvironmentMixin`, `EnvironmentId` (A1).
- Produces:
  - `AttributeValue = str | int | float | bool | None | list[str | int | float]` in `osiki/models/base.py`.
  - `User` gains `name: str | None = None` and `attributes: dict[str, AttributeValue] = {}`.
  - `Tenant(Document, EnvironmentMixin, TimestampMixin, SoftDeleteMixin)` with `external_id: str`, `name: str`, `attributes: dict[str, AttributeValue] = {}`; unique `(environment_id, external_id)`.
  - `TenantMember(Document, EnvironmentMixin, TimestampMixin)` with `tenant_id: str` (tenant external id) and `user_id: str` (user external id); unique `(environment_id, tenant_id, user_id)`.
  - `BaseTenantRepository`: `upsert(external_id: str, name: str, attributes: dict[str, AttributeValue]) -> Tenant`, `get_by_external_id(external_id: str) -> Tenant | None`, `get_many(external_ids: list[str]) -> list[Tenant]`.
  - `BaseTenantMemberRepository`: `add(tenant_id: str, user_id: str) -> None` (idempotent), `remove(tenant_id: str, user_id: str) -> bool`, `is_member(tenant_id: str, user_id: str) -> bool`, `tenants_for_user(user_id: str) -> list[str]`, `members(tenant_id: str, skip: int, limit: int) -> list[str]`.
  - `BaseUserRepository.upsert_by_external_id(external_id: str, name: str | None, email: str | None, attributes: dict[str, AttributeValue] | None) -> User`. A `None` argument leaves that field unchanged.
  - Routes:
    - `PUT /users/by-external/{external_id}` with body `UserUpsert{name?, email?, attributes?}` → 200 `UserRead`, where `UserRead` gains `name` and `attributes`.
    - `PUT /tenants/{external_id}` with body `TenantUpsert{name: str, attributes?}` → 200 `TenantRead{external_id, name, attributes, created_at, updated_at}`.
    - `GET /tenants/{external_id}` → `TenantRead`, or 404.
    - `PUT /tenants/{tenant_id}/members/{user_id}` → 204. Returns 404 if the tenant or the user (by external id) is missing.
    - `DELETE /tenants/{tenant_id}/members/{user_id}` → 204, or 404 if not a member.
    - `GET /tenants/{tenant_id}/members?page&page_size` → `PaginatedResponse[str]` of user external ids.

- [ ] **Step 1: Write failing tests.**
  - e2e:
    - `test_user_upsert_creates_then_updates`: the first PUT with `{"name":"Kofi","attributes":{"team_id":"t1"}}` gives 200 and `name == "Kofi"`. A second PUT with `{"attributes":{"team_id":"t2"}}` keeps `name == "Kofi"` and has `attributes == {"team_id":"t2"}`.
    - `test_tenant_upsert_and_get`.
    - `test_add_member_requires_existing_user_and_tenant` → 404 when either is missing.
    - `test_add_member_idempotent`: two PUTs, then members lists `["u1"]` once.
    - `test_remove_non_member_404`.
    - `test_tenant_isolated_by_environment`: a tenant upserted in env `a` gives a GET 404 in env `b`.
  - Integration repo tests: one per interface method above.
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Implement** the models, repos, mocks and factories (`make_tenant`, `make_tenant_member`), schemas and routes. Upserts use `find_one` + `insert`/`save` scoped by environment.
- [ ] **Step 4: Run the full suite.** → PASS, 100%.
- [ ] **Step 5: Commit.** `git commit -m "feat: add tenants, tenant membership and user upsert"`

### Task A3: Strict tenancy in checks and assignments

**Files:**
- Modify: `osiki/services/permission_resolver/permission_resolver.py`, `osiki/services/authorization/authorization_service.py`, `osiki/services/authorization/base_authorization_service.py`, `osiki/schemas/authorization.py`, `osiki/api/routes/authorization.py`, `osiki/api/routes/users.py`, `osiki/api/routes/groups.py`, `tests/unit/services/test_scope_matcher.py`, `tests/unit/services/test_authorization.py`, `tests/e2e/test_authorization.py`

**Interfaces:**
- Consumes: `BaseTenantMemberRepository.is_member`/`add`, `BaseTenantRepository.get_by_external_id`, `BaseUserRepository.get_by_external_id` (A2).
- Produces:
  - `AuthorizationRequest.user_id` is now the user's **external id**.
  - `AuthorizationService.__init__(permission_resolver, user_repository, tenant_member_repository)`.
  - New `denial_reason` values: `"unknown_user"` and `"not_tenant_member"`.

The scope truth table to pin. A is the assignment's scope, R is the request's scope, and `None` is treated as `{}`.

| A.tenant_id | R.tenant_id | Matches when |
|---|---|---|
| t | t | every other key in A equals R's |
| t | u ≠ t | never |
| t | absent | never |
| absent (project-wide) | t | every key in A equals R's **and** the user is a member of t (checked in the service) |
| absent | absent | every key in A equals R's |

`ScopeMatcher.matches` already implements the key-subset rule. The bug is that `PermissionResolver` skips matching when the request scope is empty (`if scope:`), so tenant-scoped assignments leak into tenantless requests.

- [ ] **Step 1: Write failing tests.**
  - `test_scope_matcher.py`: one test per row of the table, e.g. `test_tenant_assignment_never_matches_tenantless_request`: `matches({"tenant_id":"t"}, {}) is False`.
  - `test_authorization.py`:
    - `test_tenant_scoped_role_does_not_apply_without_tenant`: the user holds `docs:read` scoped to tenant `t`; `authorize(..., scope=None)` → `allowed False`.
    - `test_project_wide_role_requires_membership` (**Review Focus 1**): an unscoped role grants `docs:read`; the user isn't a member of `t`; `scope={"tenant_id":"t"}` → `allowed False`, `denial_reason == "not_tenant_member"`. After `add("t", user)` → `allowed True`.
    - `test_unknown_user_denied`: `denial_reason == "unknown_user"`.
  - `tests/e2e/test_users.py::test_tenant_scoped_assignment_adds_membership`: `POST /users/{id}/roles` with `scope.tenant_id = "t"` (tenant exists) → `GET /tenants/t/members` includes the user's external id.
  - `test_tenant_scoped_assignment_unknown_tenant_404`. Apply the same rule to group-role assignment with a tenant scope: the tenant must exist (404), and no membership is added, because a group isn't a user.
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Implement.**
  - The resolver always filters with `self._scope_matcher.matches(user_scope, scope or {})`.
  - `authorize` resolves the user by external id. If `scope` has `tenant_id` and `not is_member` → deny `not_tenant_member` before resolving permissions.
  - Pass the internal id to the resolver.
  - Update the e2e authorization tests to send external ids.
- [ ] **Step 4: Run the full suite.** → PASS, 100%.
- [ ] **Step 5: Commit.** `git commit -m "fix: enforce strict tenant isolation in authorization"`

**Checkpoint A:** suite green; the README check example works with an external user id.

---

## Phase B — Grants with conditions

### Task B1: Rule AST — validate, evaluate, residualize (pure)

**Files:**
- Create: `osiki/decision/__init__.py`, `osiki/decision/rules.py`, `tests/unit/decision/test_rules_validate.py`, `tests/unit/decision/test_rules_evaluate.py`, `tests/unit/decision/test_rules_residualize.py`

`osiki/decision/` must not import Beanie, FastAPI, loguru or anything under `osiki/` outside `osiki/decision/`. M2 vendors this package into the SDK.

**Rule AST (canonical JSON, stored and shipped as-is):**

```
Rule       := {"and": [Rule, ...1+]} | {"or": [Rule, ...1+]} | {"not": Rule} | Compare
Compare    := {"op": "eq"|"ne"|"lt"|"lte"|"gt"|"gte"|"in", "left": Operand, "right": Operand}
Operand    := {"ref": "<root>.<name>"} | {"value": Scalar | [Scalar, ...]}
root       := "record" | "user" | "tenant"
name       := ^[A-Za-z_][A-Za-z0-9_]{0,63}$     (exactly one segment after the root)
Scalar     := string | number | boolean | null
```

- `user.id` and `tenant.id` are the external ids. Any other `user.<name>` / `tenant.<name>` reads `attributes[name]`. `record.<name>` reads the record's top-level field.

**Interfaces:**
- Produces (all in `osiki/decision/rules.py`):
  - `class RuleError(ValueError)` with attributes `path: str` (e.g. `"$.and[1].left"`) and `message: str`.
  - `def validate_rule(rule: Any) -> None`. Raises `RuleError` on:
    - malformed shape or unknown keys
    - depth > 16 or more than 256 nodes
    - a Compare where both sides are `value`
    - a Compare where both sides reference `record`
    - `in` whose right operand is a `record` ref
    - `in` whose right `value` is not a list
    - an ordering op (`lt`, `lte`, `gt`, `gte`) with a list value
  - `@dataclass(frozen=True) class RuleContext: record: Mapping[str, Any] | None; user: Mapping[str, Any]; tenant: Mapping[str, Any] | None`. `user` and `tenant` include their `"id"` key alongside the attributes.
  - `def evaluate(rule: Mapping[str, Any], ctx: RuleContext) -> bool`.
  - `FilterNode = {"and": [...]} | {"or": [...]} | {"field": str, "op": "eq"|"ne"|"lt"|"lte"|"gt"|"gte"|"in"|"nin", "value": Any}`.
  - `def residualize(rule: Mapping[str, Any], user: Mapping[str, Any], tenant: Mapping[str, Any] | None) -> FilterNode | bool`. Returns `True` for all records, `False` for none, otherwise a filter tree with no `not` nodes, which SDKs translate to ORM queries.

**Evaluation semantics (three-valued, deny-safe):**
- A ref that is missing (absent key, absent record or tenant) or whose value is `None` makes its Compare **UNKNOWN**.
- Type mismatches are UNKNOWN: ordering across str and number, and `bool` vs number (`True` never equals `1`). `int` and `float` compare numerically.
- `in`: the left value is in the right list.
- `and`/`or`/`not` follow Kleene logic: `not UNKNOWN = UNKNOWN`.
- The top-level result is `True` only for TRUE. UNKNOWN → `False`.

**Residualize:** substitute `user.*` and `tenant.*` refs with their values, so a Compare referencing a missing user or tenant value becomes UNKNOWN. Fold constants (TRUE/FALSE/UNKNOWN, Kleene). Push `not` down with De Morgan and these operator negations:
- `eq` ↔ `ne`
- `lt` ↔ `gte`
- `lte` ↔ `gt`
- `in` ↔ `nin`

`not UNKNOWN` stays UNKNOWN. Normalise every leaf to `{"field", "op", "value"}`, flipping the operator when the record ref is on the right (`lt` ↔ `gt`, `lte` ↔ `gte`). At the end, UNKNOWN → `False`. Leaves carry the implicit contract that a null or missing field never matches, so SDKs must translate `ne`/`nin` as "field present and …".

- [ ] **Step 1: Write failing tests.** Key assertions:
  - validate:
    - `test_rejects_record_vs_record`: `{"op":"eq","left":{"ref":"record.a"},"right":{"ref":"record.b"}}` → `RuleError` with `path == "$"`.
    - `test_rejects_two_segment_ref`: `record.a.b`.
    - `test_rejects_in_with_record_on_right`.
    - `test_rejects_depth_17`.
    - `test_accepts_own_team`: `{"op":"eq","left":{"ref":"record.team_id"},"right":{"ref":"user.team_id"}}`.
  - evaluate (**Review Focus 3**):
    - `test_own_team_true`
    - `test_missing_record_field_is_false`
    - `test_missing_user_attribute_is_false`
    - `test_not_over_missing_field_is_false`: `{"not": own_team}` where the record lacks `team_id` → `False`.
    - `test_ne_with_null_is_false`
    - `test_bool_not_equal_one`
    - `test_int_float_equal`: `1 == 1.0` → `True`.
    - `test_in_list_literal`
    - `test_or_true_with_unknown`: TRUE or UNKNOWN → `True`.
  - residualize:
    - `test_own_team_becomes_field_filter` → `{"field":"team_id","op":"eq","value":"t1"}`.
    - `test_missing_user_attr_is_false`
    - `test_not_pushed_down`: `{"not": {"op":"lt","left":{"ref":"record.amount"},"right":{"value":100}}}` → `{"field":"amount","op":"gte","value":100}`.
    - `test_record_on_right_flips_op`
    - `test_constant_true_folds`: `{"or":[TRUEcompare, recordCompare]}` → `True`.
- [ ] **Step 2: Run them.** `poetry run pytest tests/unit/decision -v` → FAIL.
- [ ] **Step 3: Implement** `rules.py` to the semantics above. A small `Tri` enum (TRUE/FALSE/UNKNOWN) is the expected internal representation.
- [ ] **Step 4: Run them.** → PASS. `poetry run mypy osiki/decision` is clean.
- [ ] **Step 5: Commit.** `git commit -m "feat: add record rule AST with deny-safe evaluation and residual filters"`

### Task B2: Named conditions

**Files:**
- Create: `osiki/models/condition.py`, `osiki/repositories/conditions/{__init__,base_condition_repository,mongodb_condition_repository}.py`, `osiki/schemas/condition.py`, `osiki/api/routes/conditions.py`, `tests/e2e/test_conditions.py`, `tests/integration/repositories/test_condition_repository.py`
- Modify: `osiki/configs/database.py`, `osiki/main.py`, `osiki/api/routes/__init__.py`, `osiki/api/dependencies.py`, mocks/factories/conftest

**Interfaces:**
- Consumes: `validate_rule`, `RuleError` (B1).
- Produces:
  - `Condition(Document, EnvironmentMixin, TimestampMixin, SoftDeleteMixin)` with `key: str` (slug `^[a-z][a-z0-9_]{0,62}$`), `name: str`, `description: str | None`, `expression: dict[str, Any]`; unique `(environment_id, key)`.
  - `BaseConditionRepository`: `create`, `get_by_id`, `get_by_key(key: str)`, `get_by_ids(ids: list[str])`, `update`, `deactivate(condition_id: str) -> bool`, `list_active(skip, limit)`.
  - Routes `/conditions`: POST (201; 409 on duplicate key; 422 with `details={"path": e.path}` on `RuleError`), GET by id, PATCH (name, description, expression; key is immutable), DELETE (204, soft), GET list (paginated). A DELETE of a condition referenced by any active role grant → 409 `"Condition is in use"`. That check is added in B3 once grants exist; B2 ships without it.
- [ ] **Step 1: Write failing tests:**
  - `test_create_condition`
  - `test_invalid_expression_422_with_path`
  - `test_duplicate_key_409`
  - `test_key_immutable_on_patch` (the PATCH body has no `key` field; extra fields are ignored)
  - `test_list_conditions`
  - `test_condition_env_isolated`
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite.** → PASS, 100%.
- [ ] **Step 5: Commit.** `git commit -m "feat: add named record conditions"`

### Task B3: Role grants replace `permission_ids`

**Files:**
- Modify: `osiki/models/role.py`, `osiki/schemas/role.py`, `osiki/repositories/roles/*`, `osiki/api/routes/roles.py`, `osiki/api/routes/conditions.py` (in-use check), `osiki/services/permission_resolver/permission_resolver.py` (read grants; unconditional only, until B5 removes it), `scripts/migrate_m1.py`, `tests/mocks/*`, the role and resolver tests

**Interfaces:**
- Consumes: `BaseConditionRepository.get_by_id`/`get_by_ids` (B2).
- Produces:
  - `class Grant(BaseModel): permission_id: PydanticObjectId; condition_id: PydanticObjectId | None = None`.
  - `Role.grants: list[Grant] = []`. `permission_ids` is removed.
  - `RoleCreate`/`RoleUpdate`: `grants: list[GrantSchema] | None` (where `GrantSchema{permission_id: str, condition_id: str | None}`), plus `permission_ids: list[str] | None` kept as shorthand for unconditional grants. Both are merged and deduplicated on `(permission_id, condition_id)`.
  - `RoleRead.grants: list[GrantSchema]`; `RoleRead.permission_ids` is removed.
  - `BaseRoleRepository.add_permission(role_id: str, permission_id: str, condition_id: str | None = None) -> bool` and `remove_permission(role_id: str, permission_id: str, condition_id: str | None = None) -> bool`. Both act on that exact grant.
  - `BaseRoleRepository.is_condition_in_use(condition_id: str) -> bool`.
- [ ] **Step 1: Write failing tests.**
  - `test_create_role_with_conditional_grant`
  - `test_permission_ids_shorthand_becomes_unconditional_grants`
  - `test_unknown_condition_422`
  - `test_parent_role_must_exist_in_same_env`: a parent created in env `a` and referenced from env `b` → 422.
  - `test_unknown_permission_422`
  - `test_remove_exact_grant_only`: a role holds `(p, None)` and `(p, c)`; removing `(p, c)` leaves `(p, None)`.
  - `test_delete_condition_in_use_409`
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Implement.**
  - Create and update validate that every permission, condition and parent exists in the current environment (422 `ValidationError` naming the missing id).
  - Extend `scripts/migrate_m1.py`: for role docs that have `permission_ids` and no `grants`, set `grants = [{"permission_id": p, "condition_id": None} ...]` and `$unset` `permission_ids`.
- [ ] **Step 4: Run the full suite.** → PASS, 100%.
- [ ] **Step 5: Commit.** `git commit -m "feat: replace role permission_ids with grants that can carry conditions"`

### Task B4: Pure decision core and conformance fixtures

**Files:**
- Create: `osiki/decision/models.py`, `osiki/decision/scope.py`, `osiki/decision/decide.py`, `tests/unit/decision/test_decide.py`, `tests/unit/decision/test_list_filter.py`, `conformance/README.md`, `conformance/decisions/*.json`, `conformance/filters/*.json`, `tests/conformance/test_conformance.py`
- Modify: `osiki/services/scope_matcher/scope_matcher.py` (delegates to `decision.scope.scope_matches`)

**Interfaces:**
- Consumes: `evaluate`, `residualize`, `RuleContext`, `FilterNode` (B1).
- Produces (pydantic models in `osiki/decision/models.py`, all `frozen=True`):
  - `GrantEntry{permission: str ("res:act"), condition: str | None (condition key)}`
  - `RoleEntry{id: str, name: str, parent_id: str | None, grants: list[GrantEntry]}`
  - `ConstraintEntry{id: str, name: str, type: str, config: dict[str, Any]}`
  - `Snapshot{environment_id: str, version: int, roles: list[RoleEntry], conditions: dict[str, dict[str, Any]], constraints: list[ConstraintEntry]}`
  - `AssignmentEntry{role_id: str, scope: dict[str, str], expires_at: float | None, via: Literal["direct","group"]}`
  - `UserBundle{user_id: str, attributes: dict[str, Any], tenants: dict[str, dict[str, Any]] (tenant external id → attributes), assignments: list[AssignmentEntry]}`
  - `DecisionRequest{resource: str, action: str, scope: dict[str, str] = {}, record: dict[str, Any] | None = None, now: float}`
  - `Decision{allowed: bool, matched_permission: str | None, matched_via: Literal["direct","group"] | None, condition: str | None, denial_reason: Literal["no_permission","not_tenant_member","condition_failed","record_required"] | None}`
  - `EffectiveGrant{permission: str, condition: str | None, via: Literal["direct","group"]}`
  - `FilterResult{mode: Literal["all","none","filter"], filter: FilterNode | None}`
  - `osiki/decision/scope.py`: `def scope_matches(assignment_scope: Mapping[str, str], request_scope: Mapping[str, str]) -> bool` (the Task A3 table, without the membership row).
  - `osiki/decision/decide.py`:
    - `def decide(snapshot: Snapshot, bundle: UserBundle, request: DecisionRequest) -> Decision`
    - `def effective_grants(snapshot: Snapshot, bundle: UserBundle, scope: Mapping[str, str], now: float) -> list[EffectiveGrant]`
    - `def list_filter(snapshot: Snapshot, bundle: UserBundle, resource: str, action: str, scope: Mapping[str, str], now: float) -> FilterResult`

**`decide` algorithm (pin exactly):**
1. If `scope` has `tenant_id` not in `bundle.tenants` → deny `not_tenant_member`.
2. Keep assignments with `expires_at is None or expires_at > now`, and `scope_matches(a.scope, scope)`.
3. For each kept assignment, walk the role and its ancestors via `parent_id`. Stop at a missing role, and stop when an id repeats (a cycle). Collect `(grant, via)`.
4. A grant matches when its permission is one of these, in specificity order: `res:act`, `res:*`, `*:act`, `*:*`.
5. If any matching grant has `condition is None` → allow. Use the most specific match; among equals, `direct` beats `group`.
6. Otherwise, if any matching grants are conditional:
   - If `record is None` → deny `record_required`.
   - Otherwise evaluate each condition in specificity order with `RuleContext(record, {"id": user_id, **attributes}, {"id": tenant_id, **tenants[tenant_id]} or None)`. Skip condition keys missing from the snapshot. The first `True` → allow, with `condition` set.
   - None true → deny `condition_failed`.
7. No matching grants → deny `no_permission`.

**`list_filter`:** apply steps 1–4. An unconditional match → `all`. Otherwise OR the `residualize` results of the matching conditional grants: any `True` → `all`; all `False` or no matches → `none`; else `filter` with `{"or": [...]}`, or the single node when there's one.

- [ ] **Step 1: Write failing tests.** Port the meaningful cases from `tests/unit/services/test_authorization.py` and `test_permission_resolver.py` (exact, wildcard, inheritance, cycle, expiry, group via) into `test_decide.py` as pure snapshot/bundle tests, and add:
  - `test_conditional_wildcard_applies_condition` (**Review Focus 4**): the grant is `invoices:*` with `own_team`; a request for `invoices:delete` with a same-team record → allowed, `condition == "own_team"`, `matched_permission == "invoices:*"`. With no record → `record_required`.
  - `test_unconditional_beats_conditional`: one role holds `invoices:read`, another holds `invoices:read` with `own_team`; a request with no record → allowed.
  - `test_unknown_condition_key_skipped` → `condition_failed`.
  - `test_not_tenant_member`
  - `test_tenant_attributes_visible_to_rules`
  - `test_list_filter_all_none_filter`: one test each for the three modes.
- [ ] **Step 2: Write the conformance fixtures.**
  - Each `conformance/decisions/<name>.json` is `{"name", "snapshot", "bundle", "request", "expected": Decision}`.
  - Each `conformance/filters/<name>.json` is `{"name", "snapshot", "bundle", "resource", "action", "scope", "now", "expected": FilterResult}`.
  - At minimum, one decision case per test in Step 1, plus one per evaluate test in B1, expressed as decisions.
  - `tests/conformance/test_conformance.py` parametrises over every file and asserts `decide(...) == expected`.
  - `conformance/README.md` documents the format and the three-valued semantics for SDK authors.
- [ ] **Step 3: Run them.** `poetry run pytest tests/unit/decision tests/conformance -v` → FAIL.
- [ ] **Step 4: Implement** `models.py`, `scope.py` and `decide.py`. Point `ScopeMatcher.matches` at `scope_matches`.
- [ ] **Step 5: Run the full suite.** → PASS, 100%.
- [ ] **Step 6: Commit.** `git commit -m "feat: add pure decision core with conformance fixtures"`

### Task B5: Server decides through snapshot + bundle; config version

**Files:**
- Create: `osiki/models/environment_state.py`, `osiki/repositories/environment_state/{__init__,base_environment_state_repository,mongodb_environment_state_repository}.py`, `osiki/services/snapshot_builder/{__init__,snapshot_builder}.py`, `osiki/services/bundle_builder/{__init__,bundle_builder}.py`, `tests/unit/services/test_snapshot_builder.py`, `tests/unit/services/test_bundle_builder.py`
- Modify: the role, permission, condition and constraint Mongo repos (bump version on writes), `osiki/services/authorization/*`, `osiki/schemas/authorization.py`, `osiki/api/routes/authorization.py`, `osiki/api/routes/permissions.py`, `osiki/api/dependencies.py`
- Delete: `osiki/services/permission_resolver/`, `tests/unit/services/test_permission_resolver.py` (cases already ported in B4)

**Interfaces:**
- Consumes: `decide`, `effective_grants`, `Snapshot`, `UserBundle` (B4); all repos.
- Produces:
  - `EnvironmentState(Document)` with `environment_id: str` (unique) and `config_version: int = 0`.
  - `BaseEnvironmentStateRepository(environment_id)`: `get_config_version() -> int` (0 if absent) and `bump_config_version() -> int` (atomic `$inc` with upsert).
  - The Role, Permission, Condition and Constraint repos take `(environment_id: str, state: BaseEnvironmentStateRepository)` and call `bump_config_version()` after every successful create, update, deactivate, `add_permission` and `remove_permission`.
  - `SnapshotBuilder(environment_id, state_repo, role_repo, permission_repo, condition_repo, constraint_repo)` with `async build() -> Snapshot`. The cache is a module-level `dict[str, Snapshot]` keyed by environment; it rebuilds when the stored `version != get_config_version()`. Roles become `RoleEntry` with grants rendered as `"res:act"` strings and condition keys. Inactive roles, permissions and conditions are excluded.
  - `BundleBuilder(user_repo, user_role_repo, user_group_repo, group_role_repo, tenant_member_repo, tenant_repo)` with `async build(user_external_id: str) -> UserBundle | None`.
  - `AuthorizationService(snapshot_builder, bundle_builder)` with `authorize(user_id: str, resource: str, action: str, scope: dict[str, str] | None = None, record: dict[str, Any] | None = None) -> AuthorizationResult`. `AuthorizationResult` gains `condition: str | None`. An unknown user → `unknown_user`.
  - `AuthorizationRequest` gains `record: dict[str, Any] | None = None`; `AuthorizationResponse` gains `condition`.
  - `GET /permissions/users/{user_id}/effective?tenant_id=` takes the external user id and returns `list[EffectiveGrantRead{permission, condition, via}]`.
- [ ] **Step 1: Write failing tests.**
  - `test_version_bumps_on_every_config_write` (**Review Focus 5**): parametrised over role create, update, deactivate, `add_permission`, `remove_permission`; permission create and deactivate; condition create, update and deactivate; constraint create, update and deactivate. Each strictly increases `get_config_version()`.
  - `test_snapshot_cached_until_version_changes`: build twice and assert one repo read (spy on the mock); bump, build, and assert the reads happen again.
  - `test_snapshot_excludes_inactive`
  - `test_bundle_flattens_group_assignments_with_via_group`
  - `test_bundle_includes_tenant_attributes`
  - e2e `test_check_with_record_and_condition`: set up the `own_team` condition, a role with a conditional `invoices:read`, a user with `team_id`, a tenant and an assignment; `POST /authorization/check` with a same-team record → allowed and `condition == "own_team"`; a different-team record → `condition_failed`.
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Implement.** Delete the resolver package and its dependency wiring. `PermissionResolverDep` is removed from `dependencies.py`.
- [ ] **Step 4: Run the full suite.** → PASS, 100%. `poetry run mypy osiki` is clean.
- [ ] **Step 5: Commit.** `git commit -m "feat: authorize through snapshot and bundle with config versioning"`

**Checkpoint B:** server checks and the conformance fixtures go through the same `decide()`.

---

## Phase C — Export, enforcement, logging

### Task C1: Snapshot, bundle and filter endpoints

**Files:**
- Create: `osiki/api/routes/snapshot.py`, `tests/e2e/test_snapshot.py`
- Modify: `osiki/api/routes/users.py`, `osiki/api/routes/authorization.py`, `osiki/schemas/authorization.py`, `osiki/api/routes/__init__.py`, `osiki/main.py`

**Interfaces:**
- Consumes: `SnapshotBuilder`, `BundleBuilder`, `list_filter` (B4/B5).
- Produces:
  - `GET /snapshot` → `Snapshot` JSON with header `ETag: "<version>"`. Request header `If-None-Match: "<version>"` matching the current version → 304 with an empty body.
  - `GET /snapshot/version` → `{"version": int}`.
  - `GET /users/by-external/{external_id}/bundle` → `UserBundle`, or 404.
  - `POST /authorization/filter` with body `FilterRequest{user_id, resource, action, scope?}` → `FilterResult`. An unknown user → `{"mode":"none","filter":null}`.
- [ ] **Step 1: Write failing tests:**
  - `test_snapshot_etag_and_304`
  - `test_snapshot_version_endpoint_tracks_writes`
  - `test_bundle_404_unknown_user`
  - `test_bundle_contents`
  - `test_filter_own_team_returns_field_filter`: `{"mode":"filter","filter":{"field":"team_id","op":"eq","value":"t1"}}`.
  - `test_filter_unconditional_returns_all`
  - `test_snapshot_env_isolated`
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite.** → PASS, 100%.
- [ ] **Step 5: Commit.** `git commit -m "feat: expose snapshot, user bundle and list filter endpoints"`

### Task C2: Enforce constraints on every assignment path

**Files:**
- Modify: `osiki/services/constraint_validator/constraint_validator.py` (env-scoped repos), `osiki/api/routes/users.py` (role assignment, group membership), `osiki/api/routes/groups.py` (group-role assignment), `osiki/api/exceptions.py` (if a 409 helper is needed), `tests/e2e/test_users.py`, `tests/e2e/test_groups.py`

**Interfaces:**
- Consumes: `ConstraintValidatorDep` (exists, currently unused), `BaseUserGroupRepository`, `BaseGroupRoleRepository`.
- Produces: a violation returns 409 `ConflictError("Constraint violated", details={"constraint": name, "reason": reason})`. These paths call `validate(user_id, role_id, scope)`:
  - `POST /users/{id}/roles`: validate the user and role.
  - `POST /groups/{id}/roles`: validate for every active member of the group; the first violation blocks.
  - `POST /users/{id}/groups`: validate the user against every active role assignment of the group.
- [ ] **Step 1: Write failing tests:**
  - `test_mutual_exclusion_blocks_direct_assignment`: roles initiator and approver.
  - `test_mutual_exclusion_blocks_group_role_assignment`
  - `test_mutual_exclusion_blocks_joining_group`
  - `test_cardinality_per_tenant_counts_only_this_env`
  - `test_prerequisite_blocks_assignment`
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Implement.** The validator receives env-bound repos through the existing dependency.
- [ ] **Step 4: Run the full suite.** → PASS, 100%.
- [ ] **Step 5: Commit.** `git commit -m "feat: enforce constraints on direct, group-role and group-membership assignment"`

### Task C3: Access logging off the request path

**Files:**
- Create: `osiki/api/routes/access_logs.py`, `osiki/schemas/access_log.py`, `tests/e2e/test_access_logs.py`
- Modify: `osiki/models/access_log.py`, `osiki/repositories/access_logs/*`, `osiki/api/routes/authorization.py`, `osiki/configs/settings.py`, `osiki/api/routes/__init__.py`, `osiki/main.py`

**Interfaces:**
- Produces:
  - `AccessLog` gains `EnvironmentMixin`, `tenant_id: str | None` and `source: Literal["server","sdk"] = "server"`.
  - `BaseAccessLogRepository.create_many(logs: list[AccessLog]) -> int`.
  - `AppSettings.access_log_success_sample_rate: float = 0.1`.
  - `/authorization/check` schedules the log write with FastAPI `BackgroundTasks`. It records every denial, and records successes when `random.random() < access_log_success_sample_rate`. `latency_ms` is the decide time.
  - `POST /access-logs/batch` with body `{"entries": list[AccessLogIngest]}` (1–500 entries; each has `timestamp, user_id, resource, action, scope, allowed, matched_permission?, condition?, denial_reason?, latency_ms`) → 202 `{"accepted": n}`. Stored with `source="sdk"`. More than 500 entries → 422.
- [ ] **Step 1: Write failing tests:**
  - `test_denial_always_logged`
  - `test_success_sampled`: monkeypatch `random.random` to 0.5 with rate 0.1 → not logged; 0.05 → logged.
  - `test_batch_ingest_202_and_stored_as_sdk`
  - `test_batch_over_500_rejected`
  - `test_logs_env_scoped`
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite** plus quality checks: `poetry run pytest --cov=osiki && make lint && make typecheck` → PASS, 100%.
- [ ] **Step 5: Update docs.** Update `README.md`:
  - the environment header
  - the check request's external `user_id` and optional `record`
  - a conditions example
  - the snapshot, bundle and filter endpoints
  - a link to `conformance/README.md`
- [ ] **Step 6: Commit.** `git commit -m "feat: move access logging off the request path and add SDK batch ingest"`

**Checkpoint C / M1 done:** the full suite is green at 100%. `scripts/migrate_m1.py` runs cleanly twice against a local Mongo that holds pre-M1 data (manual check: `make up`, seed data on `main`, switch branch, run the script twice, and get the same counts the second time with no errors).
