# M3a — Engine: Tenant Team and Role Manager — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the engine everything a business owner (a tenant admin) needs in order to manage their own team safely:
- tenant-owned roles, developer role templates, and permissions marked "owners may hand out";
- a no-escalation check and a last-manager guard;
- atomic team operations, each of which writes an audit entry with a trusted actor.

This is all exposed under `/api/v1/tenants/{tenant_id}/team/…`, and released as engine tag `v0.3.0`.

**Architecture:**
- **Trusted actor.** A front door (the Osiki Cloud gateway) sets the `X-Osiki-Actor` header. The engine trusts it the same way it trusts `X-Osiki-Environment`: the engine is never exposed directly.
- **TeamService.** A new `TeamService` runs every team operation inside a `UnitOfWork` (a Mongo multi-document transaction when `MONGODB_TRANSACTIONS=true`, a no-op otherwise). Each operation:
  1. checks that the actor may manage the tenant (`osiki.team:manage`);
  2. runs the no-escalation and constraint checks;
  3. writes the change and one `AuditLog` entry.
- **How tenant roles reach the SDK.** Tenant-owned roles ship to SDKs inside the user's `UserBundle` (a new `roles` field), never in the environment snapshot. `decide` looks a role id up in both. An older SDK ignores the field and fails closed.

**Tech Stack:** Python 3.13, FastAPI, Beanie 2 on pymongo's `AsyncMongoClient`, pytest + pytest-asyncio, mongomock-motor for unit/e2e tests, real `mongo:7` (single-node replica set) for the transaction tests.

**Spec:**
- `docs/superpowers/specs/2026-10-18-osiki-cloud-design.md`, §4 (account and tenancy model, tenant admins), §5.7 (end-customer role manager), §8 (M3).
- The Osiki Cloud M3 design (private repo `osiki-cloud`, `docs/superpowers/specs/2026-10-19-m3-role-manager-design.md`). Every engine-relevant decision from it is restated in Global Constraints below, so this plan stands alone.

Prior work: `docs/superpowers/plans/2026-10-19-m2a-python-sdk.md`, `conformance/README.md`.

## Global Constraints

- **Engine conventions (unchanged from M2a):**
  - Python `>=3.13,<3.14`, mypy strict, ruff `E F I N W UP`, black 88, coverage `fail_under = 100`.
  - Every `Base*Repository` method is mirrored on its `Mock*Repository`; every new model gets a `make_*` factory in `tests/mocks/factories.py`.
  - Every repository is environment-bound (`__init__(environment_id, …)`). CI runs `mypy .` over the whole repo.
- **Decision core:** `osiki/decision/` stays Python 3.11-compatible and pure. After any change to it, run `python scripts/sync_sdk_decision.py`; `make sdk-test` must pass.
- **Actor header:** `X-Osiki-Actor` has one of two forms:
  - `developer:<id>`
  - `tenant_user:<user_external_id>`
  
  An absent header means `developer:anonymous` (self-hosted use with no front door). Anything else gets 400 `ValidationError`.
- **Built-ins:**
  - The resource prefix `osiki.` is reserved: `POST /permissions` refuses it with 422.
  - The only built-in permission in M3 is `osiki.team:manage` (resource `osiki.team`, action `manage`).
  - The default template is the role named `Owner`, with `tenant_id=None`, `is_template=True`, `is_system=True` and grants `[osiki.team:manage]`.
- **Assignable:**
  - `Permission.assignable` defaults to `False`.
  - An `osiki.*` permission can never be marked assignable (422).
  - Only assignable permissions may appear in a tenant role's grants.
- **Templates offered to a tenant:** an active project role with `is_template=True` whose every grant is either assignable or an `osiki.*` built-in. A tenant role may be copied only from an offered template.
- **Tenant roles:**
  - `Role.tenant_id` is set, and `parent_role_id` is always `None`.
  - Names are unique per (environment, tenant). A project role and a tenant role may share a name.
  - A tenant role's grants never contain `osiki.*`.
  - Writes to tenant roles bump `assignments_version`, never `config_version`.
- **No-escalation (tenant_user actors only; developers are exempt):** every grant an actor puts into a role, or gives through an assignment, must be covered by a grant the actor effectively holds in that tenant:
  - **Permission:** held `a:b` covers wanted `c:d` iff each part of the held permission is `*` or equals the wanted part. So `invoices:*` covers `invoices:read` and `invoices:*`, but `*:read` does not cover `invoices:*`.
  - **Condition:** an unconditional held grant covers any condition; a conditional held grant covers only the same condition key.
  - **Assigning a role** requires covering all of that role's grants, including `osiki.team:manage` when assigning `Owner`. That is how owners hand on management.
  - **Later losses:** losing permissions later changes nothing already made.
- **Last-manager guard:** a tenant must always keep at least one user who effectively holds `osiki.team:manage` in it, directly or via a group, unexpired. Any revoke or removal that would leave zero is refused with 409 `last_manager`.
- **Atomicity:** each team operation is a single unit of work, with its audit entry inside it.
- **Audit:** `AuditLog` gains a top-level, indexed `tenant_id`. Retention stays at 2 years.
- **Error bodies:** keep the existing `api/exceptions.py` shapes. New 409 reasons are passed as `details={"reason": …}`, with the values `last_manager`, `escalation`, `not_assignable`, `role_in_use`, `not_offered`.
- **Release:** engine tag `v0.3.0` after merge, pushed only on the owner's confirmation.

## Review Focus

1. **A `tenant_user` actor on another tenant's path:** a `tenant_user` actor whose user is not a member of the path's tenant, or holds no `osiki.team:manage` there, gets 403 on every team route, reads included. Pinned in Task 9.
2. **An older SDK seeing a bundle that references a tenant role:** an SDK without `bundle.roles` support treats the unknown role id as missing and denies. Pinned by the conformance fixture `tenant_role_missing_from_both_denies` in Task 4.
3. **Two managers removing each other at the same moment:** with exactly two managers revoking each other concurrently, one succeeds and one gets 409 `last_manager`. Pinned by the real-Mongo test in Task 7.
4. **A developer un-marks a permission that tenant roles already use:** existing grants keep working, the editor stops offering the permission, and the next edit of such a role must drop it, or it gets 409 `not_assignable`. Pinned in Task 6.
5. **A template deactivated after it was copied:** copies keep working, the template is no longer offered, and constraints on the template still bind the copies. Pinned in Task 8.

---

### Task 1: Trusted actor, audit writer and audit read endpoint

**Files:**
- Create: `osiki/api/actor.py`, `osiki/services/audit/__init__.py`, `osiki/services/audit/audit_writer.py`, `osiki/api/routes/audit_logs.py`, `osiki/schemas/audit_log.py`
- Modify: `osiki/models/audit_log.py`, `osiki/repositories/audit_logs/base_audit_log_repository.py`, `osiki/repositories/audit_logs/mongodb_audit_log_repository.py`, `tests/mocks/repositories.py`, `tests/mocks/factories.py`, `osiki/api/dependencies.py`, `osiki/api/routes/__init__.py`, `osiki/main.py`, `tests/e2e/conftest.py`
- Test: `tests/unit/test_actor.py`, `tests/unit/services/test_audit_writer.py`, `tests/integration/repositories/test_audit_log_repository.py`, `tests/e2e/test_audit_logs.py`

**Interfaces:**
- Produces:
  - `Actor(type: Literal["developer", "tenant_user"], id: str)`, a frozen pydantic model.
  - `get_actor(x_osiki_actor: str | None = Header(None)) -> Actor`, and `ActorDep = Annotated[Actor, Depends(get_actor)]`.
  - `AuditLog.tenant_id: str | None = None`.
  - `BaseAuditLogRepository.list(tenant_id: str | None, skip: int, limit: int, session: AsyncClientSession | None = None) -> list[AuditLog]`, newest first. `tenant_id=None` returns every entry.
  - `AuditWriter(repo).record(actor: Actor, action: str, target_type: str, target_id: str, *, tenant_id: str | None, before: dict | None, after: dict | None, session=None) -> AuditLog`.
  - `GET /api/v1/audit-logs?tenant_id=&page=&page_size=` → `PaginatedResponse[AuditLogRead]`.
  - `POST /api/v1/audit-logs` with `{action, target_type, target_id, tenant_id?, before?, after?}` → 201 `AuditLogRead`, recorded with the header actor. It lets a front door log its own events (invites) in the same trail. A front door must never let outside callers reach it.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_actor.py
def test_absent_header_is_anonymous_developer():
    assert get_actor(None) == Actor(type="developer", id="anonymous")

def test_parses_tenant_user():
    assert get_actor("tenant_user:u-42") == Actor(type="tenant_user", id="u-42")

@pytest.mark.parametrize("raw", ["", "tenant_user:", "admin:x", "developer", "tenant_user:a:b:c "])
def test_malformed_is_validation_error(raw):
    with pytest.raises(ValidationError):
        get_actor(raw)

# tests/unit/services/test_audit_writer.py
async def test_record_writes_top_level_tenant_and_actor():
    entry = await AuditWriter(MockAuditLogRepository("env")).record(
        Actor(type="tenant_user", id="u1"), "role.create", "role", "r1",
        tenant_id="t1", before=None, after={"name": "Cashier"})
    assert (entry.tenant_id, entry.actor_type, entry.actor_id) == ("t1", "tenant_user", "u1")
    assert entry.changes.after == {"name": "Cashier"}

# tests/e2e/test_audit_logs.py
def test_post_records_with_header_actor(client):
    r = client.post("/api/v1/audit-logs", headers={"X-Osiki-Actor": "tenant_user:u1"},
                    json={"action": "invite.create", "target_type": "invite", "target_id": "i1", "tenant_id": "t1"})
    assert r.status_code == 201 and r.json()["actor_id"] == "u1"

def test_list_filters_by_tenant_newest_first(client, seed_audit):  # seeds t1 x2, t2 x1
    body = client.get("/api/v1/audit-logs", params={"tenant_id": "t1"}).json()
    assert [i["tenant_id"] for i in body["items"]] == ["t1", "t1"]
    assert body["items"][0]["timestamp"] >= body["items"][1]["timestamp"]
```

The id pattern after the colon is `^[A-Za-z0-9._@-]{1,128}$`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `poetry run pytest tests/unit/test_actor.py tests/unit/services/test_audit_writer.py tests/e2e/test_audit_logs.py -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement**
- **Model:** add `tenant_id` to `AuditLog`, plus the index `[("environment_id",1),("tenant_id",1),("timestamp",DESCENDING)]`.
- **Repository:** add `list` to the base, Mongo and mock repositories, with `session` threaded into the Mongo `find` call.
- **Route:** register `audit_logs_router` in `routes/__init__.py`, `main.py` and the e2e conftest.

- [ ] **Step 4: Run tests**

Run: `poetry run pytest -q && poetry run mypy . && poetry run ruff check .`
Expected: all pass, coverage 100%.

- [ ] **Step 5: Commit** `feat: trusted actor header and tenant-indexed audit log`

---

### Task 2: Unit of work (Mongo transactions) and the real-Mongo test harness

**Files:**
- Create: `osiki/services/unit_of_work.py`, `scripts/realmongo-test.sh`, `tests/realmongo/__init__.py`, `tests/realmongo/conftest.py`, `tests/realmongo/test_unit_of_work.py`
- Modify:
  - `osiki/configs/settings.py` (`mongodb_transactions: bool = False`);
  - `osiki/configs/database.py`: keep the client as `get_client() -> AsyncMongoClient`, and raise `RuntimeError` before `initialize_database`;
  - `osiki/api/dependencies.py` (`UnitOfWorkDep`);
  - `pyproject.toml`: register the pytest marker `realmongo` and exclude `tests/realmongo` from coverage collection;
  - `Makefile` (`test-realmongo`);
  - the write methods listed below, on the base, Mongo and mock repositories.
- Test: `tests/unit/services/test_unit_of_work.py`, `tests/realmongo/test_unit_of_work.py`

**Interfaces:**
- Produces:
  - `class UnitOfWork(ABC)`, whose `transaction()` is an async context manager yielding `AsyncClientSession | None`.
  - `MongoUnitOfWork(client, enabled: bool)`. When enabled, it opens a session plus `start_transaction()` and commits on a clean exit; when disabled, it yields `None`.
  - `NullUnitOfWork()` always yields `None`.
  - `get_unit_of_work() -> UnitOfWork`, which builds `MongoUnitOfWork(get_client(), settings.mongodb_transactions)`.
- **Optional `session` keyword:** these methods gain `session: AsyncClientSession | None = None` (keyword-only, passed through to Beanie `insert`/`save`/`find`/`update`):
  - `UserRepository.upsert_by_external_id`
  - `TenantMemberRepository.add`, `.remove`, `.is_member`
  - `UserRoleRepository.create`, `.revoke`, `.get_user_roles`, `.get_by_tenant`, `.find_assignment`
  - `RoleRepository.create`, `.update`, `.deactivate`, `.get_by_id`
  - `EnvironmentStateRepository.bump_assignments_version`
  - `AuditLogRepository.create`
- **Mocks:** mock repositories accept `session` and ignore it.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/services/test_unit_of_work.py
async def test_disabled_mongo_uow_yields_none():
    async with MongoUnitOfWork(client=object(), enabled=False).transaction() as s:
        assert s is None

async def test_null_uow_yields_none():
    async with NullUnitOfWork().transaction() as s:
        assert s is None

# tests/realmongo/test_unit_of_work.py   (marked realmongo; skipped unless OSIKI_TEST_MONGO_URL)
async def test_failure_rolls_back_role_and_audit(realmongo_env):
    uow = MongoUnitOfWork(get_client(), enabled=True)
    with pytest.raises(RuntimeError):
        async with uow.transaction() as s:
            await realmongo_env.roles.create(make_role(name="X"), session=s)
            await realmongo_env.audit.create(make_audit_log(), session=s)
            raise RuntimeError("boom")
    assert await realmongo_env.roles.get_by_name("X") is None
    assert await realmongo_env.audit.list(None, 0, 10) == []
```

`scripts/realmongo-test.sh`:
1. Starts `mongo:7 --replSet rs0 --bind_ip_all` on a random free localhost port, with no auth.
2. Runs `rs.initiate()` and waits for PRIMARY.
3. Exports `OSIKI_TEST_MONGO_URL=mongodb://127.0.0.1:<port>/?replicaSet=rs0&directConnection=true`.
4. Runs `poetry run pytest -m realmongo tests/realmongo -v`.
5. Always removes the container (trap).

- [ ] **Step 2: Run to verify fail** — `poetry run pytest tests/unit/services/test_unit_of_work.py -v` → FAIL (ImportError).
- [ ] **Step 3: Implement** the unit of work, the settings and the session threading. `tests/realmongo/conftest.py` inits Beanie on `OSIKI_TEST_MONGO_URL` with a fresh database per test, and sets `mongodb_transactions=True`.
- [ ] **Step 4: Verify** — `poetry run pytest -q` (realmongo skipped, 100% coverage) and `make test-realmongo` → PASS.
- [ ] **Step 5: Commit** `feat: unit of work with optional Mongo transactions`

---

### Task 3: Model flags, reserved built-ins and environment bootstrap

**Files:**
- Create: `osiki/api/routes/environment.py` (bootstrap), `osiki/services/builtins.py`, `scripts/migrate_m3.py`
- Modify:
  - `osiki/models/permission.py` (`assignable: bool = False`);
  - `osiki/models/role.py`, adding `tenant_id: str | None = None`, `is_template: bool = False` and `copied_from: PydanticObjectId | None = None`, and replacing the unique index `(environment_id, name)` with `(environment_id, tenant_id, name)`, plus an index `(environment_id, tenant_id, is_active)`;
  - `osiki/schemas/permission.py`, `osiki/schemas/role.py` (`is_template` on create/read/update, `tenant_id` and `copied_from` read-only);
  - `osiki/api/routes/permissions.py`, adding `PATCH /permissions/{id}` with `{assignable?, description?}` and refusing `osiki.` resources on create;
  - `osiki/api/routes/roles.py`: project roles only, so list/get/patch/delete ignore or 404 any role with `tenant_id` set, and `get_by_name` is project-scoped;
  - `osiki/repositories/roles/*`, adding `get_by_name(name, tenant_id: str | None = None)`, `list_tenant(tenant_id)` and `list_templates()`;
  - `osiki/repositories/permissions/*`, adding `update(permission)`;
  - mocks and factories;
  - `routes/__init__.py`, `main.py`, the e2e conftest.
- Test: `tests/e2e/test_permissions.py`, `tests/e2e/test_roles.py`, `tests/e2e/test_environment_bootstrap.py`, `tests/integration/test_migrate_m3.py`

**Interfaces:**
- Produces:
  - `BUILTIN_TEAM_MANAGE = ("osiki.team", "manage")`, `OWNER_TEMPLATE_NAME = "Owner"`.
  - `async def ensure_builtins(permission_repo, role_repo) -> Builtins`, where `Builtins(team_manage_permission_id: str, owner_role_id: str)`. It is idempotent and never duplicates.
  - `PUT /api/v1/environment/bootstrap` → `200 {"team_manage_permission_id": …, "owner_role_id": …}`.
  - `is_builtin(permission: Permission) -> bool` (resource starts with `osiki.`).
  - The migration `scripts/migrate_m3.py [--mongodb-url …] [--database …]` (defaults from `AppSettings`, so `python scripts/migrate_m3.py` works inside the engine image, which copies the repo) drops the old `environment_id_1_name_1` index if present, then lets Beanie create the new indexes. It is idempotent.

- [ ] **Step 1: Write failing tests**

```python
def test_bootstrap_is_idempotent(client):
    a = client.put("/api/v1/environment/bootstrap").json()
    b = client.put("/api/v1/environment/bootstrap").json()
    assert a == b
    owner = client.get(f"/api/v1/roles/{a['owner_role_id']}").json()
    assert (owner["name"], owner["is_template"], owner["is_system"]) == ("Owner", True, True)

def test_reserved_prefix_refused(client):
    r = client.post("/api/v1/permissions", json={"resource": "osiki.team", "action": "x"})
    assert r.status_code == 422

def test_builtin_cannot_be_marked_assignable(client):
    pid = client.put("/api/v1/environment/bootstrap").json()["team_manage_permission_id"]
    assert client.patch(f"/api/v1/permissions/{pid}", json={"assignable": True}).status_code == 422

def test_mark_assignable(client, make_permission_via_api):
    pid = make_permission_via_api("invoices", "read")
    body = client.patch(f"/api/v1/permissions/{pid}", json={"assignable": True}).json()
    assert body["assignable"] is True

def test_project_roles_api_hides_tenant_roles(client, tenant_role_in_db):
    assert client.get(f"/api/v1/roles/{tenant_role_in_db}").status_code == 404
    assert tenant_role_in_db not in [r["id"] for r in client.get("/api/v1/roles").json()["items"]]

async def test_migrate_m3_drops_old_name_index(mongo_db_with_m2_indexes):
    await migrate_m3(mongo_db_with_m2_indexes)
    names = [ix["name"] for ix in await mongo_db_with_m2_indexes.roles.list_indexes().to_list()]
    assert "environment_id_1_name_1" not in names
```

- [ ] **Step 2: Run** the new tests → FAIL.
- [ ] **Step 3: Implement.** The snapshot builder must render only roles with `tenant_id is None`. Add a test to `tests/unit/services/test_snapshot_builder.py`: `test_snapshot_excludes_tenant_roles`.
- [ ] **Step 4: Verify** — `poetry run pytest -q && poetry run mypy .` → PASS.
- [ ] **Step 5: Commit** `feat: assignable permissions, role templates and environment bootstrap`

---

### Task 4: Tenant roles in the user bundle (decision core, conformance, SDK sync)

**Files:**
- Modify: `osiki/decision/models.py` (`UserBundle.roles`), `osiki/decision/decide.py`, `osiki/services/bundle_builder/bundle_builder.py`, `osiki/api/dependencies.py` (BundleBuilder gets role, permission and condition repos), `conformance/README.md`
- Create:
  - `conformance/decisions/tenant_role_in_bundle_grants.json`
  - `conformance/decisions/tenant_role_id_clash_snapshot_wins.json`
  - `conformance/decisions/tenant_role_missing_from_both_denies.json`
  - `conformance/filters/tenant_role_in_bundle_filters.json`
- Regenerate: `sdks/python/src/osiki_sdk/_decision/*` via `python scripts/sync_sdk_decision.py`
- Test: `tests/unit/decision/test_decide.py`, `tests/unit/services/test_bundle_builder.py`, `tests/conformance/test_conformance.py` (unchanged runner)

**Interfaces:**
- Produces:
  - `UserBundle.roles: list[RoleEntry] = Field(default_factory=list)`: the tenant-owned roles that the user's assignments reference.
  - In `decide`, `effective_grants` and `list_filter`, the role lookup becomes `{**{r.id: r for r in bundle.roles}, **{r.id: r for r in snapshot.roles}}`. On an id clash the snapshot wins, so a bundle can never override a project role.
  - `BundleBuilder.build` fills `roles` with active tenant roles (`tenant_id is not None`) referenced by any active assignment, rendered with the same rules as the snapshot's `_role_entry`. Move `_role_entry` and `_condition_key` to `osiki/services/snapshot_builder/render.py` and import them from both builders.

- [ ] **Step 1: Write failing tests.** Fixture `tenant_role_in_bundle_grants`: the snapshot has no roles. The bundle has tenant `t1`, an assignment `{"role_id": "tr1", "scope": {"tenant_id": "t1"}, "via": "direct"}`, and `roles: [{"id": "tr1", "name": "Weekend cashier", "grants": [{"permission": "sales:create"}]}]`. The request is `sales:create` in scope `{"tenant_id": "t1"}`. Expected: `allowed: true`, matched `sales:create`, via `direct`. The other fixtures:
  - `…clash_snapshot_wins`: the snapshot role `r1` grants nothing, and a bundle role with the same id `r1` grants `sales:create`. Expected: deny `no_permission`.
  - `…missing_from_both_denies`: an assignment to `tr9` that neither holds. Expected: deny `no_permission`.
  - The filter fixture: a tenant role with a conditional grant, giving `mode: "filter"`.
  
  Bundle builder test: `test_bundle_carries_only_referenced_active_tenant_roles`.
- [ ] **Step 2: Run** `poetry run pytest tests/conformance tests/unit/decision tests/unit/services/test_bundle_builder.py -v` → FAIL.
- [ ] **Step 3: Implement**, then run `python scripts/sync_sdk_decision.py`.
- [ ] **Step 4: Verify** — `poetry run pytest -q && make sdk-test` → PASS (both the engine conformance run and the SDK's own conformance run).
- [ ] **Step 5: Commit** `feat: ship tenant-owned roles in the user bundle`

---

### Task 5: No-escalation and visibility rules (pure)

**Files:**
- Create: `osiki/services/team/__init__.py`, `osiki/services/team/escalation.py`
- Test: `tests/unit/services/team/test_escalation.py`

**Interfaces:**
- Produces:
  - `covers(held: EffectiveGrant | GrantEntry, wanted: GrantEntry) -> bool`
  - `uncovered(held: Sequence[EffectiveGrant], wanted: Sequence[GrantEntry]) -> list[GrantEntry]`, in wanted order, deduplicated
  - `is_builtin_permission(permission: str) -> bool`, true for `"osiki.…:…"`

- [ ] **Step 1: Write failing tests** (one parametrized table)

```python
@pytest.mark.parametrize("held,wanted,ok", [
    (("invoices:read", None), ("invoices:read", None), True),
    (("invoices:*", None), ("invoices:read", None), True),
    (("invoices:*", None), ("invoices:*", None), True),
    (("*:read", None), ("invoices:*", None), False),
    (("*:*", None), ("*:read", None), True),
    (("invoices:read", None), ("invoices:read", "own"), True),
    (("invoices:read", "own"), ("invoices:read", None), False),
    (("invoices:read", "own"), ("invoices:read", "own"), True),
    (("invoices:read", "own"), ("invoices:read", "branch"), False),
    (("invoices:read", None), ("invoices:write", None), False),
])
def test_covers(held, wanted, ok):
    assert covers(GrantEntry(permission=held[0], condition=held[1]),
                  GrantEntry(permission=wanted[0], condition=wanted[1])) is ok
```

Plus `test_uncovered_keeps_wanted_order_and_dedupes`.

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement.** Split each permission string on its single `:` (both parts are colon-free by `PermissionPart`).
- [ ] **Step 4: Verify → PASS.**
- [ ] **Step 5: Commit** `feat: no-escalation coverage rules`

---

### Task 6: TeamService — authorization, roles (create, copy, edit, delete) and the offered templates

**Files:**
- Create: `osiki/services/team/team_service.py`, `osiki/services/team/models.py`
- Modify: `osiki/api/dependencies.py` (`get_team_service(tenant_id, actor, …)`, `TeamServiceDep`)
- Test: `tests/unit/services/team/test_team_roles.py`

**Interfaces:**
- Consumes: `Actor` (T1), `UnitOfWork` (T2), `ensure_builtins`/`is_builtin` (T3), `BundleBuilder`/`SnapshotBuilder`/`effective_grants` (T4), `covers`/`uncovered` (T5), `AuditWriter` (T1).
- Produces, in `osiki/services/team/models.py`:
  - `TeamRole(id: str, name: str, kind: Literal["template", "tenant"], grants: list[GrantEntry], copied_from: str | None, holders: int)`
  - `TeamError(OsikiError)` subclasses that map to HTTP:
    - `NotManager` → 403
    - `EscalationRefused(uncovered: list[GrantEntry])` → 409 `escalation`
    - `NotAssignable(permissions: list[str])` → 409 `not_assignable`
    - `NotOffered` → 409 `not_offered`
    - `RoleInUse` → 409 `role_in_use`
    - `LastManager` → 409 `last_manager`
- Produces, `TeamService(environment_id, tenant_id, actor, *, repos…, snapshot_builder, bundle_builder, validator, uow, audit)` with:
  - `async def require_manager() -> None`:
    - A developer always passes.
    - A tenant_user must be an active member of `tenant_id` and effectively hold `osiki.team:manage` in scope `{"tenant_id": tenant_id}`.
    - Otherwise raise `NotManager`.
    - Every public method below calls it first.
  - `async def list_roles() -> list[TeamRole]`: the offered templates (Global Constraints), then this tenant's active roles, each with its holder count in this tenant.
  - `async def create_role(name: str, grants: list[GrantRef], copied_from: str | None) -> TeamRole`, where `GrantRef(permission_id: str, condition_id: str | None)`.
  - `async def update_role(role_id: str, name: str | None, grants: list[GrantRef] | None) -> TeamRole`
  - `async def delete_role(role_id: str) -> None`
- **Write rules**, applied in this order:
  1. `require_manager`.
  2. Reference validation (existing helpers in `routes/roles.py`; move `_validate_references` into `osiki/services/roles/validation.py` and reuse it).
  3. Every grant permission is active, assignable and not built-in, otherwise `NotAssignable`.
  4. `copied_from`, if given, is an offered template, otherwise `NotOffered`.
  5. For a tenant_user, `uncovered(actor_effective, grants)` is empty, otherwise `EscalationRefused`.
  6. Name unique in the tenant (`ConflictError`).
  7. Inside `uow.transaction()`: write the role (`tenant_id` set, `parent_role_id=None`), bump `assignments_version`, and record the audit entry (`role.create` / `role.update` / `role.delete`, `target_type="role"`, before/after = name plus permission strings).
- `delete_role` refuses with `RoleInUse` while any active assignment of the role exists in the tenant.
- `update_role` and `delete_role` only touch roles whose `tenant_id` equals this tenant; any other id gives `NotFoundError`.

- [ ] **Step 1: Write failing tests**, each using the mock repos and `NullUnitOfWork`:
  - `test_developer_creates_tenant_role_without_holding_it`
  - `test_tenant_user_without_team_manage_is_refused` (`NotManager`)
  - `test_manager_cannot_add_permission_they_lack` (`EscalationRefused`, with `uncovered == [refunds:create]`)
  - `test_unassignable_permission_refused` and `test_builtin_permission_refused` (`NotAssignable`)
  - `test_copy_from_unoffered_template_refused` (a template with one non-assignable non-builtin grant → `NotOffered`)
  - `test_copy_records_copied_from`
  - `test_same_name_allowed_in_other_tenant_and_as_project_role`
  - `test_delete_refused_while_held` (`RoleInUse`)
  - `test_each_write_bumps_assignments_version_not_config_version`
  - `test_each_write_records_one_audit_entry_with_tenant_and_actor`
  - **Review Focus 4:** `test_unmarked_permission_existing_role_keeps_working_but_edit_must_drop_it`. After the developer flips `assignable` off, `list_roles` still shows the grant, a bundle still grants it, and `update_role` with the grant kept raises `NotAssignable`.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement.** The actor's effective grants come from `effective_grants(await snapshot_builder.build(), bundle, {"tenant_id": tenant_id}, time.time())`, with the bundle from `bundle_builder.build(actor.id)`. A `None` bundle means `NotManager`.
- [ ] **Step 4: Verify → PASS** (100% coverage).
- [ ] **Step 5: Commit** `feat: tenant team service — roles`

---

### Task 7: TeamService — members, assignments, the last-manager guard, effective view and dry run

**Files:**
- Modify: `osiki/services/team/team_service.py`, `osiki/services/team/models.py`
- Test: `tests/unit/services/team/test_team_members.py`, `tests/realmongo/test_last_manager_race.py`

**Interfaces:**
- Produces:
  - `TeamMember(user_id: str, name: str | None, email: str | None, roles: list[TeamRoleRef])`, with `TeamRoleRef(id: str, name: str, kind: Literal["template","tenant"])`.
  - `EffectiveSource(permission: str, condition: str | None, role_id: str, role_name: str, via: Literal["direct","group"])`.
  - `Violation(kind: Literal["escalation","not_assignable","not_offered","constraint","last_manager"], message: str, details: dict[str, str])`.
- Produces, on TeamService:
  - `async def list_members(skip: int = 0, limit: int = 100) -> list[TeamMember]`
  - `async def add_member(user_id: str, *, name: str | None, email: str | None, role_id: str) -> TeamMember`. In ONE unit of work it:
    1. upserts the user;
    2. adds membership;
    3. assigns the role in scope `{"tenant_id": tenant_id}`;
    4. bumps `assignments_version`;
    5. records one audit entry `member.add`.

    The role must be an offered template or this tenant's role. Escalation is checked against all of the role's grants, so assigning `Owner` requires holding `osiki.team:manage`. Constraints are checked via the existing `ConstraintValidator.validate(user_id, role_id, scope)`; Task 8 later makes it see group roles and templates, without changing that call.
  - `async def assign_role(user_id: str, role_id: str) -> TeamMember` (audit `assignment.create`)
  - `async def revoke_role(user_id: str, role_id: str) -> None` (audit `assignment.revoke`, last-manager guard)
  - `async def remove_member(user_id: str) -> None`: revokes every assignment in this tenant and removes the membership (audit `member.remove`, last-manager guard).
  - `async def effective(user_id: str) -> list[EffectiveSource]`: per applying assignment, the role's own grants with that role's id and name. Grants from a template show the template.
  - `async def validate(op: Literal["create_role","update_role","assign_role","add_member","revoke_role","remove_member"], **args) -> list[Violation]`: runs the same checks as the real operation without writing. It never raises a `TeamError`; it returns them as violations. The `add_member` dry run never requires the user to exist (the real operation upserts it), so a front door can check an invite before the invitee has an account.
- **Last-manager guard:** inside the same unit of work, count tenant members who would still effectively hold `osiki.team:manage` after the change (direct or group assignments, unexpired, scope `tenant_id`). Zero means `LastManager`. To make concurrent revokes conflict under transactions, every guarded write also performs a `$inc` on a per-tenant counter document, `TenantTeamLock(environment_id, tenant_id, version)` (new model in `osiki/models/tenant_team_lock.py`, registered in `configs/database.py`). Two concurrent transactions then write-conflict, and the loser retries once and re-evaluates the guard.

- [ ] **Step 1: Write failing tests**
  - `test_add_member_creates_user_membership_assignment_and_one_audit_entry`
  - `test_add_member_with_owner_requires_holding_team_manage` (a tenant_user holding only Cashier → `EscalationRefused`)
  - `test_owner_can_hand_on_management` (a tenant_user owner adds a member with `Owner` → OK)
  - `test_revoking_last_manager_refused` and `test_removing_last_manager_refused` (`LastManager`)
  - `test_second_manager_can_be_removed_when_one_remains`
  - `test_group_held_manage_counts_for_guard`
  - `test_expired_manage_assignment_does_not_count`
  - `test_effective_lists_role_sources`
  - `test_validate_returns_violations_without_writing` (state and audit unchanged)
  - **Review Focus 3:** `tests/realmongo/test_last_manager_race.py::test_two_managers_revoking_each_other_concurrently`. Under `asyncio.gather`, exactly one succeeds, one raises `LastManager`, and one manager remains.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify** — `poetry run pytest -q && make test-realmongo` → PASS.
- [ ] **Step 5: Commit** `feat: tenant team service — members and last-manager guard`

---

### Task 8: Constraint fixes for tenant roles

**Files:**
- Modify: `osiki/services/constraint_validator/constraint_validator.py`, `osiki/services/constraint_validator/base_constraint_validator.py`, `osiki/repositories/user_roles/*` (`count_active(role_ids, scope_filter, now)`), mocks
- Test: `tests/unit/services/test_constraint_validator.py`

**Interfaces:**
- Produces: `ConstraintValidator.validate(user_id, role_id, scope, *, now: float | None = None, session=None) -> ConstraintValidationResult`. Same result type; `now` defaults to `time.time()`.
- **Canonical role id:** a role's canonical id for constraint matching is `copied_from` if set, else its own id. Constraints match on canonical ids, so a constraint on a template binds every copy (D5).
- **Fixes:**
  - mutual exclusion and prerequisite consider the user's direct AND group-derived active, unexpired roles in the same tenant scope;
  - cardinality counts exclude expired assignments;
  - `per_scope` counts assignments whose scope equals the requested scope exactly (all keys).

- [ ] **Step 1: Write failing tests:**
  - `test_mutual_exclusion_sees_group_held_role`
  - `test_prerequisite_satisfied_by_group_held_role`
  - `test_cardinality_ignores_expired`
  - `test_per_scope_counts_matching_scope_only`
  - `test_constraint_on_template_binds_copy`
  - **Review Focus 5:** `test_deactivated_template_still_binds_existing_copies`
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement.** Fetch the roles via `role_repo.get_by_ids` to resolve canonical ids; the validator gains `role_repository` and `group_role_repository`, `user_group_repository` dependencies. Update `get_constraint_validator`.
- [ ] **Step 4: Verify → PASS** (existing constraint e2e tests unchanged).
- [ ] **Step 5: Commit** `fix: constraints see group roles, skip expired, honour per_scope and templates`

---

### Task 9: Team routes

**Files:**
- Create: `osiki/api/routes/team.py`, `osiki/schemas/team.py`
- Modify: `osiki/api/exceptions.py` (handlers for the `TeamError` subclasses: 403/409 with `details.reason`, plus `details.uncovered` / `details.permissions` where applicable), `osiki/api/routes/__init__.py`, `osiki/main.py`, `tests/e2e/conftest.py`
- Test: `tests/e2e/test_team.py`

**Interfaces:**
- Consumes: `TeamServiceDep` (T6/T7).
- Produces, under the prefix `/api/v1/tenants/{tenant_id}/team`:

  | Method | Path | Body | Response |
  |---|---|---|---|
  | GET | `/roles` |  | `list[TeamRoleRead]` |
  | POST | `/roles` | `{name, grants: [{permission_id, condition_id?}], copied_from?}` | 201 `TeamRoleRead` |
  | PATCH | `/roles/{role_id}` | `{name?, grants?}` | `TeamRoleRead` |
  | DELETE | `/roles/{role_id}` |  | 204 |
  | GET | `/members?page&page_size` |  | `PaginatedResponse[TeamMemberRead]` |
  | POST | `/members` | `{user_id, name?, email?, role_id}` | 201 `TeamMemberRead` |
  | PUT | `/members/{user_id}/roles/{role_id}` |  | `TeamMemberRead` |
  | DELETE | `/members/{user_id}/roles/{role_id}` |  | 204 |
  | DELETE | `/members/{user_id}` |  | 204 |
  | GET | `/members/{user_id}/effective` |  | `list[EffectiveSourceRead]` |
  | POST | `/validate` | `{op, args}` | `{violations: [ViolationRead]}` |
  | GET | `/permissions` |  | assignable, non-builtin active permissions as `list[PermissionRead]` (for the role editor) |
  | GET | `/audit-logs?page&page_size` |  | this tenant's entries (`require_manager` applies) |

  A tenant that doesn't exist gets 404 on every route.

- [ ] **Step 1: Write failing tests:**
  - the full owner flow (bootstrap, a developer makes `u-owner` the Owner, then as `X-Osiki-Actor: tenant_user:u-owner`):
    1. create Weekend cashier;
    2. add `u-staff` with it;
    3. fetch the bundle for `u-staff`;
    4. assert `decide` allows `sales:create` and denies `refunds:create` in `t1`;
  - `test_manager_escalation_is_409_with_uncovered`
  - `test_last_manager_is_409`
  - `test_validate_reports_violation_and_writes_nothing`
  - `test_tenant_audit_lists_only_this_tenant`
  - **Review Focus 1:** `test_tenant_user_of_other_tenant_gets_403_on_every_route`, which loops over every route in the table with the actor of tenant `t2` on path `t1`.
  - `test_malformed_actor_header_is_400`
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify** — `poetry run pytest -q && poetry run mypy . && make sdk-test` → PASS.
- [ ] **Step 5: Commit** `feat: tenant team API`

---

### Task 10: Docs, version and release prep

**Files:**
- Modify: `README.md` (a "Team management for your customers" section: the actor header contract, a warning never to expose the engine without a front door that sets `X-Osiki-Actor`, the bootstrap call, the transaction setting, `scripts/migrate_m3.py`), `pyproject.toml` (version `0.3.0`), `conformance/README.md` (`bundle.roles`), `docker-compose.yml` (the dev `mongodb` gets `--replSet rs0`, plus an init healthcheck running `rs.initiate`; the dev `.env` example sets `MONGODB_TRANSACTIONS=true`)
- Test: none new. Run the full gates.

- [ ] **Step 1:** Write the docs.
- [ ] **Step 2: Verify:**
  - `poetry run pytest -q`
  - `poetry run mypy .`
  - `poetry run ruff check . && poetry run black --check .`
  - `make sdk-test`
  - `make test-realmongo`
  - `make docker-smoke`

  All must pass.
- [ ] **Step 3: Commit** `docs: M3 team management, v0.3.0`
- [ ] **Step 4:** Open the PR. After merge, and only on the owner's confirmation, tag `v0.3.0` on the merge commit.
