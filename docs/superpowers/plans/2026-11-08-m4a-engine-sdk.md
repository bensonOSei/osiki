# M4a: Engine v0.4.0 and Python SDK 0.3.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the engine gaps found while building the team dashboard on v0.3.0, and give the Python SDK a way to declare an app's permissions in code.

**Architecture:** Every change is additive to the HTTP API (new optional fields, new endpoints), so v0.3.0 clients keep working unchanged. No data migration: new behaviour reads existing fields (`updated_at`, `copied_from`, `TenantMember.created_at`). Team-API changes stay inside `TeamService` and its rule helpers; project-API changes stay in `osiki/api/routes/`.

**Tech Stack:** Python 3.13, FastAPI, Beanie/MongoDB, pytest (100% coverage gate), mypy strict, ruff + black; SDK: httpx, its own pytest suite (`make sdk-test`).

**Spec:** none separate. The decisions below (D1-D10) are the spec; each task cites the ones it implements.

## Decisions (the spec)

- **D1. Owners are offered every active project template.** A template is the developer's own definition, so `assignable` no longer hides it. `assignable` keeps governing only (a) which permissions an owner may put in a role they make, and (b) what a copy can carry. Assigning a template still runs the no-escalation check (the assigner must hold everything it grants). Replaces the rule in `_offered_templates` ("every grant is assignable or built-in").
- **D2. A team role PATCH never silently drops grants.** When `grants` is sent, the stored role's grants the caller could not see (grants on inactive permissions) are kept. Grants already on the role that the caller sends back unchanged are accepted even if their permission is no longer assignable or their condition was deleted ("grandfathered"); only grants new to the role must pass the assignable and reference checks. Escalation is checked on new grants only, as today. Basis: an inactive permission grants nothing until reactivated.
- **D3. Optimistic concurrency on team role edits.** `TeamRoleRead` gains `updated_at: float`. `TeamRoleUpdate` gains `expected_updated_at: float | None = None`. When it is set and differs from the stored value, the PATCH is refused with 409, `details.reason = "stale"`. Omitted: today's behaviour.
- **D4. Templates show their inherited grants.** In `TeamRoleRead`, a template's `grants` include the grants of its active ancestors (the lineage `_lineage` already walks), deduplicated; each `GrantEntryRead` gains `inherited_from: str | None` (the ancestor role's name; `None` = the role's own grant). A copy therefore sees everything the template really grants.
- **D5. `GET /team/conditions`** (manager only): active conditions as `[{id, key, description}]`, so a team role editor can offer them. `GrantRefIn` already accepts `condition_id`.
- **D6. Atomic role replace.** `POST /team/members/{user_id}/roles/replace` with `{from_role_id, to_role_id}` swaps one direct assignment for another in one unit of work. Rules are those of revoke-then-assign, evaluated on the end state: the last-manager guard passes when `to` also grants `osiki.team:manage`. One audit entry, action `assignment.replace`. `validate` gains op `replace_role`. Same id for both: 422.
- **D7. Richer team audit entries** (the `changes` dicts; no schema change):
  - `assignment.create`, `assignment.revoke`, `assignment.replace`: before/after carry `roles`, the member's full direct role-name list (sorted) before and after the write.
  - `role.create` for a copy: `after.copied_from = {"id": ..., "name": ...}`.
  - `member.add` after, and `member.remove` before: add `name` and `email`.
  - `TeamMemberRead` gains `member_since: float | None` (the `TenantMember.created_at`).
- **D8. Template usage counts.** `GET /roles/usage?role_id=A&role_id=B` (project API, up to 100 ids) returns `[{role_id, tenants, copies}]`: `tenants` = distinct tenants with a live (unexpired) assignment of the role, direct or via group, in this environment; `copies` = active tenant roles with `copied_from` = the role. One query per kind, never per tenant.
- **D9. Project API writes are audited.** Roles and permissions create/update/delete record entries with `tenant_id=None` and the `X-Osiki-Actor` actor. Actions: `role.create|update|delete` (target `role`), `permission.create|update|delete` (target `permission`). Role state: `{name, is_template, grants: [permission strings, "perm?cond-key" when conditional]}`. Permission state: `{permission, description, assignable, is_active}`.
- **D10. Role names: 409, never 500.** Project create refuses a name held by any project role, active or deleted (the unique index covers both). Project rename gets the same pre-check. Both also catch `DuplicateKeyError` (race) as 409. `GET /roles` reports a real `total`.
- **SDK. `osiki.permissions.ensure(specs)`** creates the app's missing permissions in the key's environment and updates description/assignable where a spec sets them. Never deletes or deactivates. SDK version 0.3.0 (0.2.0 was never published; 0.3.0 supersedes it).

## Global Constraints

- `make test` passes with 100% line and branch coverage; `make typecheck` (mypy strict) and `make lint` clean; `make sdk-test` passes.
- API changes are additive only: no field removed or renamed, no response shape of an existing endpoint narrowed, no existing status code changed except 500 → 409 (D10).
- No data migration script.
- New error sentences follow the existing style ("Role with this name already exists").
- This is a public repo: no names of hosted services, customers or hosts in code, tests, docs or commits.
- Commit message trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- Replacing the last manager's only managing role with a non-managing role must be refused (`last_manager`), while swapping between two managing roles must succeed. Pinned in Task 6.
- A PATCH that sends a grant identical to a kept hidden grant must not duplicate it. Pinned in Task 4.
- A template granting a permission the assigning owner lacks is now offered (D1) but assigning it must still be refused (`escalation`). Pinned in Task 3.
- `expected_updated_at` must compare equal after a JSON round trip of the value the API returned. Pinned in Task 4.
- `ensure()` run twice is a no-op the second time; a spec matching a deleted permission raises a clear SDK error naming it instead of an HTTP traceback. Pinned in Task 9.

---

### Task 1: Role names give 409, and `GET /roles` reports a real total (D10)

**Files:**
- Modify: `osiki/api/routes/roles.py` (`create_role`, `update_role`, `list_roles`)
- Modify: `osiki/repositories/roles/base_role_repository.py`, `osiki/repositories/roles/mongodb_role_repository.py`
- Modify: `tests/mocks/repositories.py`
- Test: `tests/e2e/test_roles.py`, `tests/integration/repositories/` (role repository test file there)

**Interfaces:**
- Produces: `BaseRoleRepository.name_in_use(name: str, tenant_id: str | None = None) -> bool` (any row, active or not); `BaseRoleRepository.count_active_project() -> int`.

- [ ] **Step 1: Write the failing tests** in `tests/e2e/test_roles.py`:
  - `test_create_role_reusing_deleted_name_409`: create "Auditor", delete it, create "Auditor" again → 409, `details == {"name": "Auditor"}`.
  - `test_rename_role_to_taken_name_409`: roles "A" and "B"; PATCH B `{"name": "A"}` → 409.
  - `test_rename_role_duplicate_key_race_409`: monkeypatch the repo's `update` to raise `pymongo.errors.DuplicateKeyError` → 409 (same for `create`, `test_create_role_duplicate_key_race_409`).
  - `test_list_roles_total_counts_all_pages`: 3 roles, `page_size=2` → page 1 `total == 3`.
- [ ] **Step 2: Run** `poetry run pytest tests/e2e/test_roles.py -k "409 or total" -v`. Expected: FAIL (500s, wrong total).
- [ ] **Step 3: Implement.** Add the two repo methods (Mongo and the mock). `create_role` pre-checks `name_in_use(data.name)`; `update_role` pre-checks when the name changes; both wrap the repo write and map `DuplicateKeyError` to `ConflictError("Role with this name already exists", details={"name": ...})`. `list_roles` uses `count_active_project()` for `total`.
- [ ] **Step 4: Run** `make test`. Expected: PASS, 100%.
- [ ] **Step 5: Commit** `fix: role name conflicts are 409, and the role list reports its total`.

### Task 2: Audit project role and permission writes (D9)

**Files:**
- Modify: `osiki/api/routes/roles.py`, `osiki/api/routes/permissions.py`
- Modify: `osiki/api/dependencies.py` (an `AuditWriterDep` built from `AuditLogRepository`, if none exists)
- Test: `tests/e2e/test_roles.py`, `tests/e2e/test_permissions.py`

**Interfaces:**
- Consumes: `AuditWriter.record(actor, action, target_type, target_id, *, tenant_id, before, after)`, `ActorDep`.
- Produces: `role_audit_state(role: Role, permissions: Mapping[str, str], conditions: Mapping[str, str]) -> dict[str, Any]` and `permission_audit_state(p: Permission) -> dict[str, Any]` in `osiki/services/audit/project_state.py` (new file).

- [ ] **Step 1: Write the failing tests:**
  - `test_role_writes_are_audited`: with header `X-Osiki-Actor: developer:dev-1`, create, update (rename + grants) and delete a role; `GET /audit-logs` returns `role.create`, `role.update`, `role.delete` with `actor_id == "dev-1"`, `tenant_id is None`, and `changes.after == {"name": ..., "is_template": False, "grants": ["sales:create"]}` for the create.
  - `test_permission_writes_are_audited`: create, PATCH `{"assignable": true}`, delete → `permission.create|update|delete`; the update has `before.assignable is False`, `after.assignable is True`.
  - `test_conditional_grant_audit_string`: a grant with a condition renders as `"sales:create?own-branch"` in the role state.
- [ ] **Step 2: Run** them. Expected: FAIL (no entries).
- [ ] **Step 3: Implement** the two state helpers and record one entry per write, after the write succeeds. Delete records `before` = the state just before deactivation, `after=None`.
- [ ] **Step 4: Run** `make test`. Expected: PASS, 100%.
- [ ] **Step 5: Commit** `feat: audit project role and permission changes`.

### Task 3: Team reads: every template offered, inherited grants shown, conditions listed, member since (D1, D4, D5, D7 `member_since`)

**Files:**
- Modify: `osiki/services/team/team_service.py` (`_offered_templates`, `_render`, `_member`, new `list_conditions`)
- Modify: `osiki/services/team/models.py` (`GrantEntry.inherited_from`, `TeamMember.member_since`, new `TeamCondition`)
- Modify: `osiki/schemas/team.py` (`GrantEntryRead.inherited_from`, `TeamMemberRead.member_since`, new `TeamConditionRead`)
- Modify: `osiki/api/routes/team.py` (`GET /conditions`)
- Modify: tenant member repository (base, Mongo, mock): `joined_at(tenant_id: str, user_id: str) -> float | None`
- Test: `tests/unit/services/team/test_team_roles.py`, `tests/unit/services/team/test_team_members.py`, `tests/e2e/test_team.py`

**Interfaces:**
- Produces: `GrantEntry(permission: str, condition: str | None, inherited_from: str | None = None)`; `TeamCondition(id: str, key: str, description: str | None)`; `TeamService.list_conditions() -> list[TeamCondition]`; `TeamMember.member_since: float | None`.

- [ ] **Step 1: Write the failing tests:**
  - `test_template_with_unassignable_permission_is_offered`: template "Cashier" grants `refunds:create` with `assignable=False` → it appears in `list_roles()`.
  - `test_assigning_offered_template_still_checks_escalation`: an owner lacking `refunds:create` assigns that template → `EscalationRefused`.
  - `test_copy_of_template_with_unassignable_grant_refuses_that_grant`: `create_role(copied_from=cashier, grants=[refunds])` → `NotAssignable`; without the refunds grant → succeeds.
  - `test_template_render_includes_inherited_grants`: template "Senior" with parent "Base" (grants `sales:read`) and own `sales:create` → grants `[sales:create (inherited_from None), sales:read (inherited_from "Base")]`; an inactive parent contributes nothing.
  - `test_list_conditions_active_only` and `test_list_conditions_requires_manager` (non-manager → `NotManager`).
  - `test_member_since_is_join_time`: member added at a frozen time T has `member_since == T`; a user with no membership row gets `None`.
  - e2e `test_team_conditions_endpoint`: `GET .../team/conditions` → 200 `[{"id", "key", "description"}]`.
- [ ] **Step 2: Run** `poetry run pytest tests/unit/services/team tests/e2e/test_team.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** `_offered_templates` returns `list_templates()` unfiltered (D1); `NotOffered` and `_assignable_role` follow automatically. `_render` walks `_lineage` for `kind == "template"` only, appending ancestor grants not already present (key: permission + condition) with `inherited_from = ancestor.name`. Escalation and holder checks keep using the role's own effective grants as today.
- [ ] **Step 4: Run** `make test`. Expected: PASS, 100%.
- [ ] **Step 5: Commit** `feat: offer every template to owners, show inherited grants, list conditions`.

### Task 4: Team role PATCH keeps hidden grants and refuses stale edits (D2, D3)

**Files:**
- Modify: `osiki/services/team/team_service.py` (`_check_update_role`, `_check_grants`, `update_role`, `_render` gains `updated_at`)
- Modify: `osiki/services/team/models.py` (`TeamRole.updated_at`, new `StaleRole` conflict with reason `"stale"`)
- Modify: `osiki/schemas/team.py` (`TeamRoleRead.updated_at`, `TeamRoleUpdate.expected_updated_at`, `UpdateRoleArgs` inherits it)
- Modify: `osiki/api/routes/team.py`
- Test: `tests/unit/services/team/test_team_roles.py`, `tests/e2e/test_team.py`

**Interfaces:**
- Consumes: Task 3's `_render`.
- Produces: `TeamService.update_role(role_id: str, name: str | None, grants: list[GrantRef] | None, expected_updated_at: float | None = None) -> TeamRole`; `_check_grants(grants: list[GrantRef], *, existing: Sequence[Grant] = ()) -> tuple[list[GrantEntry], list[GrantRef]]` (grants equal to an `existing` one skip the assignable and reference checks).

- [ ] **Step 1: Write the failing tests:**
  - `test_patch_keeps_grant_on_inactive_permission`: role holds `sales:create` and `old:thing`; deactivate `old:thing`; PATCH grants `[sales:create, sales:read]` → stored grants are `sales:create, sales:read, old:thing`; reactivating `old:thing` shows it again.
  - `test_patch_resending_hidden_grant_does_not_duplicate`: same setup, PATCH includes `old:thing`'s ref explicitly → stored once.
  - `test_patch_keeps_grandfathered_unassignable_grant`: role holds `refunds:create`; switch it to `assignable=False`; PATCH resending it plus a name change → 200, grant kept; PATCH adding a different unassignable permission → `NotAssignable`.
  - `test_patch_keeps_grant_on_deleted_condition`: role holds `sales:create?own-branch`; delete the condition; PATCH resending it → 200 (today: "Condition not found").
  - `test_patch_with_stale_updated_at_409`: read role, update it elsewhere, PATCH with the first `updated_at` → 409, `details["reason"] == "stale"`; with the current value → 200; omitted → 200.
  - e2e `test_expected_updated_at_round_trips_json`: the `updated_at` from `GET .../team/roles` sent back as `expected_updated_at` is accepted.
  - `test_validate_update_role_stale_raises`: `validate("update_role", ...)` with a stale value raises `StaleRole` (like the real call; stale is not one of the rule violations).
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.** In `_check_update_role`: compare `expected_updated_at` with the stored `role.updated_at` first; compute `hidden` = stored grants whose permission is inactive; call `_check_grants(grants, existing=role.grants)`; new grant list = deduplicated `unique + hidden`; escalation checks only entries not already on the role.
- [ ] **Step 4: Run** `make test`. Expected: PASS, 100%.
- [ ] **Step 5: Commit** `fix: team role edits keep grants the editor cannot see, and refuse stale edits`.

### Task 5: Richer team audit entries (D7, except `member_since`)

**Files:**
- Modify: `osiki/services/team/team_service.py` (`_assignment_state`, `_member_state`, `create_role`, `add_member`, `assign_role`, `revoke_role`, `remove_member`)
- Test: `tests/unit/services/team/test_team_members.py`, `tests/unit/services/team/test_team_roles.py`

**Interfaces:**
- Produces: `_assignment_state(user_id: str, role_id: str, role: Role | None, roles: list[str]) -> dict[str, Any]`; `_member_state(user_id: str, roles: list[str], *, name: str | None, email: str | None) -> dict[str, Any]`; helper `TeamService._direct_role_names(user_id: str, session) -> list[str]` (sorted). Task 6 uses both.

- [ ] **Step 1: Write the failing tests:**
  - `test_assign_audit_carries_role_sets`: member with ["Cashier"] is given "Manager" → `before.roles == ["Cashier"]`, `after.roles == ["Cashier", "Manager"]` (existing keys `user_id`, `role_id`, `role` kept).
  - `test_revoke_audit_carries_role_sets`: the reverse.
  - `test_copy_audit_names_source`: copy of "Cashier" → `after.copied_from == {"id": <cashier id>, "name": "Cashier"}`; a role made from nothing has no `copied_from` key.
  - `test_member_add_and_remove_audit_name_email`: `after.name/email` on add, `before.name/email` on remove.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** by reading the member's direct role names inside the same session before and after the write.
- [ ] **Step 4: Run** `make test`. Expected: PASS, 100%.
- [ ] **Step 5: Commit** `feat: team audit entries carry role sets, copy source and names`.

### Task 6: Atomic role replace (D6)

**Files:**
- Modify: `osiki/services/team/team_service.py` (`replace_role`, `_check_replace_role`, `validate` op table)
- Modify: `osiki/schemas/team.py` (`TeamRoleReplace {from_role_id, to_role_id}`, `ReplaceRoleArgs`, `_ReplaceRoleOp` in the validate union, `DryRunOp` literal)
- Modify: `osiki/api/routes/team.py` (`POST /members/{user_id}/roles/replace`)
- Test: `tests/unit/services/team/test_team_members.py`, `tests/e2e/test_team.py`

**Interfaces:**
- Consumes: Task 5's `_assignment_state`, `_direct_role_names`; existing `_check_revoke_role`, `_check_assignment`, `_ensure_manager_remains`, `_assign`, `_team_write`.
- Produces: `TeamService.replace_role(user_id: str, from_role_id: str, to_role_id: str) -> TeamMember`.

- [ ] **Step 1: Write the failing tests:**
  - `test_replace_swaps_in_one_write`: Cashier → Weekend cashier; member ends with only Weekend cashier; exactly one audit entry `assignment.replace` with `before.roles == ["Cashier"]`, `after.roles == ["Weekend cashier"]`.
  - `test_replace_last_manager_to_non_manager_refused`: sole manager, Owner → Cashier → `LastManager`; nothing changed.
  - `test_replace_between_two_manager_roles_allowed`: sole manager, Owner → Manager (also grants manage) → succeeds.
  - `test_replace_escalation_refused_leaves_state`: target grants a permission the actor lacks → `EscalationRefused`; member still has the old role.
  - `test_replace_not_assigned_404`, `test_replace_target_already_assigned_409`, `test_replace_same_role_422`.
  - `test_validate_replace_role`: `validate("replace_role", ...)` returns the `last_manager` violation without writing.
  - e2e `test_team_replace_endpoint`: 200 with the `TeamMemberRead` after the swap.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** `_check_replace_role` running the revoke checks on `from` and the assign checks on `to`, with the last-manager check evaluated on the bundle after both changes (the existing `_without_direct` helper plus the `to` role's grants). `replace_role` runs check, revoke, assign and one audit record inside one `_team_write`.
- [ ] **Step 4: Run** `make test`. Expected: PASS, 100%.
- [ ] **Step 5: Commit** `feat: replace a member's role in one atomic step`.

### Task 7: Template usage counts (D8)

**Files:**
- Modify: `osiki/api/routes/roles.py` (`GET /roles/usage`, declared before `GET /roles/{role_id}`)
- Modify: `osiki/schemas/role.py` (`RoleUsageRead {role_id, tenants, copies}`)
- Modify: user-role, group-role and role repositories (base, Mongo, mock): `tenants_with_role(role_ids: list[str], now: float) -> dict[str, set[str]]` (user roles and group roles each), `copies_of(role_ids: list[str]) -> dict[str, int]`
- Test: `tests/e2e/test_roles.py`, the repository integration tests

**Interfaces:**
- Produces: `GET /roles/usage?role_id=...` (1-100 ids; more → 422) → `list[RoleUsageRead]` in request order; unknown or tenant-owned ids → `{tenants: 0, copies: 0}`.

- [ ] **Step 1: Write the failing tests:**
  - `test_role_usage_counts_distinct_tenants`: template assigned to two users in tenant A and one in tenant B, and via a group in tenant C → `tenants == 3`.
  - `test_role_usage_ignores_expired_and_other_environments`.
  - `test_role_usage_counts_active_copies`: two active copies and one deleted → `copies == 2`.
  - `test_role_usage_limits_ids`: 101 ids → 422.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** with one aggregation per collection (`$match` on environment and role ids, `$group` by role id with `$addToSet` tenant id).
- [ ] **Step 4: Run** `make test`. Expected: PASS, 100%.
- [ ] **Step 5: Commit** `feat: template usage counts`.

### Task 8: SDK `osiki.permissions.ensure` and version 0.3.0

**Files:**
- Modify: `sdks/python/src/osiki_sdk/client.py` (`list_permissions`, `create_permission`, `update_permission`)
- Modify: `sdks/python/src/osiki_sdk/osiki.py` (`_Permissions`, `Osiki.permissions`)
- Create: `sdks/python/src/osiki_sdk/permissions.py` (`PermissionSpec`, `EnsureResult`, `PermissionDeleted`)
- Modify: `sdks/python/src/osiki_sdk/__init__.py` (exports), `sdks/python/pyproject.toml` (version `0.3.0`), `sdks/python/README.md` (a "Declaring permissions" section)
- Test: `sdks/python/tests/test_permissions.py` (new; use the suite's existing HTTP mocking style)

**Interfaces:**
- Produces:
  - `PermissionSpec(resource: str, action: str, description: str | None = None, assignable: bool | None = None)` (frozen dataclass; `None` = leave as is).
  - `EnsureResult(created: list[str], updated: list[str], unchanged: list[str])` of permission strings.
  - `class PermissionDeleted(OsikiError)` naming the permission string.
  - `await osiki.permissions.ensure(specs: Sequence[PermissionSpec]) -> EnsureResult`.

- [ ] **Step 1: Write the failing tests:**
  - `test_ensure_creates_missing_and_sets_fields`: engine has none → two POSTs then PATCHes for description/assignable; result `created == ["refunds:create", "sales:create"]`.
  - `test_ensure_updates_only_differing_fields`: existing with a different description → one PATCH with only `description`; `updated == [...]`.
  - `test_ensure_twice_is_noop`: second run sends no writes; all `unchanged`.
  - `test_ensure_none_fields_left_alone`: `assignable=None` never PATCHes `assignable`.
  - `test_ensure_deleted_permission_raises`: create answers 409 → `PermissionDeleted("refunds:create")`.
  - `test_ensure_pages_through_permissions`: 150 existing permissions across two pages are all matched.
  - `test_ensure_rejects_duplicate_specs`: the same resource:action twice → `ValueError`.
- [ ] **Step 2: Run** `make sdk-test`. Expected: FAIL.
- [ ] **Step 3: Implement.** Match on `resource:action` among active permissions; create, then PATCH only the fields the spec sets that differ. Never call DELETE.
- [ ] **Step 4: Run** `make sdk-test` and `make test`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(sdk): declare permissions in code with permissions.ensure (0.3.0)`.

### Task 9: Release notes and version 0.4.0

**Files:**
- Modify: `pyproject.toml` (version `0.4.0`)
- Modify: `README.md` (API section: the new endpoints and fields from D1-D10, one line each; the D1 rule change stated plainly)
- Run: `poetry run python scripts/sync_sdk_decision.py` if the conformance fixtures need regenerating (they should not: no decision-core change)

- [ ] **Step 1: Bump the version and document** each D-item in the README.
- [ ] **Step 2: Run** `make test typecheck lint sdk-test`. Expected: all pass.
- [ ] **Step 3: Commit** `chore: release notes for v0.4.0`.
