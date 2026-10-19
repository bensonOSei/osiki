"""TeamService: authorization, role writes and the offered templates."""

import time
from collections.abc import Awaitable, Callable

import pytest
from beanie import PydanticObjectId
from pymongo.errors import DuplicateKeyError

from osiki.api.actor import Actor
from osiki.api.exceptions import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from osiki.decision.models import GrantEntry
from osiki.models.base import Scope
from osiki.models.condition import Condition
from osiki.models.permission import Permission
from osiki.models.role import Grant, Role
from osiki.services.audit.audit_writer import AuditWriter
from osiki.services.bundle_builder.bundle_builder import BundleBuilder
from osiki.services.constraint_validator.constraint_validator import ConstraintValidator
from osiki.services.snapshot_builder.snapshot_builder import (
    SnapshotBuilder,
    SnapshotCache,
)
from osiki.services.team.models import (
    EscalationRefused,
    GrantRef,
    LastManager,
    NotAssignable,
    NotManager,
    NotOffered,
    RoleInUse,
    TeamRole,
)
from osiki.services.team.team_service import TeamService
from osiki.services.unit_of_work import NullUnitOfWork
from tests.mocks import (
    MockConditionRepository,
    MockConstraintRepository,
    MockEndpointRepository,
    MockEnvironmentStateRepository,
    MockGroupRepository,
    MockGroupRoleRepository,
    MockPermissionRepository,
    MockRoleRepository,
    MockTenantMemberRepository,
    MockTenantRepository,
    MockTenantTeamLockRepository,
    MockUserGroupRepository,
    MockUserRepository,
    MockUserRoleRepository,
    make_condition,
    make_group,
    make_group_role,
    make_permission,
    make_role,
    make_user,
    make_user_role,
)
from tests.mocks.repositories import MockAuditLogRepository

TENANT = "acme"
DEVELOPER = Actor(type="developer", id="dev-1")


class Env:
    def __init__(self) -> None:
        self.state = MockEnvironmentStateRepository("default")
        self.users = MockUserRepository("default", self.state)
        self.groups = MockGroupRepository("default", self.state)
        self.user_roles = MockUserRoleRepository("default", self.state)
        self.user_groups = MockUserGroupRepository("default", self.state)
        self.group_roles = MockGroupRoleRepository("default", self.state)
        self.members = MockTenantMemberRepository("default", self.state)
        self.tenants = MockTenantRepository("default", self.state)
        self.roles = MockRoleRepository("default", self.state)
        self.permissions = MockPermissionRepository("default", self.state)
        self.conditions = MockConditionRepository("default", self.state)
        self.constraints = MockConstraintRepository("default", self.state)
        self.endpoints = MockEndpointRepository("default", self.state)
        self.audit_repo = MockAuditLogRepository("default")
        self.locks = MockTenantTeamLockRepository("default")

    def service(self, actor: Actor = DEVELOPER, tenant: str = TENANT) -> TeamService:
        bundles = BundleBuilder(
            self.users,
            self.user_roles,
            self.user_groups,
            self.groups,
            self.group_roles,
            self.members,
            self.tenants,
            self.roles,
            self.permissions,
            self.conditions,
        )
        snapshots = SnapshotBuilder(
            "default",
            self.state,
            self.roles,
            self.permissions,
            self.conditions,
            self.constraints,
            self.endpoints,
            cache=SnapshotCache(),
        )
        return TeamService(
            "default",
            tenant,
            actor,
            role_repo=self.roles,
            permission_repo=self.permissions,
            condition_repo=self.conditions,
            user_role_repo=self.user_roles,
            group_role_repo=self.group_roles,
            user_repo=self.users,
            member_repo=self.members,
            lock_repo=self.locks,
            snapshot_builder=snapshots,
            bundle_builder=bundles,
            validator=ConstraintValidator(self.constraints, self.user_roles),
            uow=NullUnitOfWork(),
            audit=AuditWriter(self.audit_repo),
        )

    async def permission(
        self,
        resource: str,
        action: str,
        *,
        assignable: bool = True,
        active: bool = True,
    ) -> Permission:
        perm = make_permission(resource, action, assignable=assignable)
        perm.is_active = active
        return await self.permissions.create(perm)

    async def condition(self, key: str) -> Condition:
        return await self.conditions.create(make_condition(key=key))

    async def manager(
        self,
        external_id: str = "mgr",
        *,
        holds: list[Permission] | None = None,
        manage: bool = True,
        tenant: str = TENANT,
        member: bool = True,
    ) -> Actor:
        """A tenant user holding (via a project role scoped to the tenant)
        osiki.team:manage and the given permissions."""
        user = await self.users.create(make_user(external_id=external_id))
        await self.tenants.upsert(tenant, tenant, {})
        if member:
            await self.members.add(tenant, external_id)
        granted = list(holds or [])
        if manage:
            granted.append(await self._manage_permission())
        role = await self.roles.create(
            make_role(
                f"held-by-{external_id}", permission_ids=[p.id for p in granted if p.id]
            )
        )
        assert user.id is not None and role.id is not None
        await self.user_roles.create(
            make_user_role(user.id, role.id, scope=Scope(tenant_id=tenant))
        )
        return Actor(type="tenant_user", id=external_id)

    async def _manage_permission(self) -> Permission:
        existing = await self.permissions.get_by_resource_action("osiki.team", "manage")
        return existing or await self.permission(
            "osiki.team", "manage", assignable=False
        )

    async def template(
        self, name: str, permissions: list[Permission], *, active: bool = True
    ) -> Role:
        role = make_role(
            name,
            permission_ids=[p.id for p in permissions if p.id],
            is_template=True,
            is_active=active,
        )
        return await self.roles.create(role)


@pytest.fixture
def env() -> Env:
    return Env()


def ref(permission: Permission, condition: Condition | None = None) -> GrantRef:
    return GrantRef(
        permission_id=str(permission.id),
        condition_id=str(condition.id) if condition else None,
    )


def entry(permission: str, condition: str | None = None) -> GrantEntry:
    return GrantEntry(permission=permission, condition=condition)


# --- authorization ---------------------------------------------------------


async def test_developer_creates_tenant_role_without_holding_it(env: Env) -> None:
    read = await env.permission("invoices", "read")

    role = await env.service().create_role("Cashier", [ref(read)], None)

    assert role.kind == "tenant"
    assert role.name == "Cashier"
    assert role.grants == [entry("invoices:read")]
    assert role.holders == 0
    stored = await env.roles.get_by_id(role.id)
    assert stored is not None
    assert stored.tenant_id == TENANT
    assert stored.parent_role_id is None
    assert stored.copied_from is None


async def test_tenant_user_without_team_manage_is_refused(env: Env) -> None:
    read = await env.permission("invoices", "read")
    actor = await env.manager("plain", holds=[read], manage=False)

    with pytest.raises(NotManager) as exc:
        await env.service(actor).create_role("Cashier", [ref(read)], None)

    assert isinstance(exc.value, AuthorizationError)
    assert exc.value.details == {"reason": "not_manager"}


async def test_unknown_user_is_not_a_manager(env: Env) -> None:
    with pytest.raises(NotManager):
        await env.service(Actor(type="tenant_user", id="ghost")).require_manager()


async def test_manager_of_another_tenant_is_not_a_manager_here(env: Env) -> None:
    actor = await env.manager("other", tenant="globex")

    with pytest.raises(NotManager):
        await env.service(actor, tenant=TENANT).require_manager()


async def test_manager_who_is_no_longer_a_member_is_refused(env: Env) -> None:
    actor = await env.manager("left", member=False)

    with pytest.raises(NotManager):
        await env.service(actor).require_manager()


async def test_conditional_manage_grant_is_not_management(env: Env) -> None:
    manage = await env._manage_permission()
    own = await env.condition("own")
    user = await env.users.create(make_user(external_id="cond"))
    await env.tenants.upsert(TENANT, TENANT, {})
    await env.members.add(TENANT, "cond")
    role = await env.roles.create(
        make_role(
            "cond-role", grants=[Grant(permission_id=manage.id, condition_id=own.id)]
        )
    )
    assert user.id is not None and role.id is not None
    await env.user_roles.create(
        make_user_role(user.id, role.id, scope=Scope(tenant_id=TENANT))
    )

    with pytest.raises(NotManager):
        await env.service(Actor(type="tenant_user", id="cond")).require_manager()


async def test_manager_passes_require_manager(env: Env) -> None:
    actor = await env.manager()

    await env.service(actor).require_manager()


async def test_expired_manage_assignment_is_not_management(env: Env) -> None:
    actor = await env.manager("temp")
    (assignment,) = await env.user_roles.get_by_tenant(TENANT)
    assignment.expires_at = time.time() - 10

    with pytest.raises(NotManager):
        await env.service(actor).require_manager()


@pytest.mark.parametrize(
    "call",
    [
        lambda svc, role: svc.list_roles(),
        lambda svc, role: svc.create_role("X", [], None),
        lambda svc, role: svc.update_role(role, "Y", None),
        lambda svc, role: svc.delete_role(role),
    ],
    ids=["list", "create", "update", "delete"],
)
async def test_every_public_method_requires_a_manager(
    env: Env, call: Callable[[TeamService, str], Awaitable[object]]
) -> None:
    stranger = Actor(type="tenant_user", id="ghost")
    role = await env.service().create_role("Existing", [], None)

    with pytest.raises(NotManager):
        await call(env.service(stranger), role.id)


# --- no escalation ---------------------------------------------------------


async def test_manager_cannot_add_permission_they_lack(env: Env) -> None:
    read = await env.permission("invoices", "read")
    refund = await env.permission("refunds", "create")
    actor = await env.manager(holds=[read])

    with pytest.raises(EscalationRefused) as exc:
        await env.service(actor).create_role("Cashier", [ref(read), ref(refund)], None)

    assert exc.value.uncovered == [entry("refunds:create")]
    assert isinstance(exc.value, ConflictError)
    assert exc.value.details["reason"] == "escalation"
    assert exc.value.details["uncovered"] == "refunds:create"
    assert await env.roles.list_tenant(TENANT) == []


async def test_manager_can_grant_what_they_hold(env: Env) -> None:
    read = await env.permission("invoices", "read")
    actor = await env.manager(holds=[read])

    role = await env.service(actor).create_role("Cashier", [ref(read)], None)

    assert role.grants == [entry("invoices:read")]


async def test_wildcard_held_grant_covers_narrower_grant(env: Env) -> None:
    every_invoice = await env.permission("invoices", "*", assignable=False)
    read = await env.permission("invoices", "read")
    actor = await env.manager(holds=[every_invoice])

    role = await env.service(actor).create_role("Cashier", [ref(read)], None)

    assert role.grants == [entry("invoices:read")]


async def test_conditional_hold_cannot_grant_unconditionally(env: Env) -> None:
    read = await env.permission("invoices", "read")
    own = await env.condition("own")
    actor = await env.manager("limited")
    # Replace the manager's role with one holding invoices:read only when "own".
    (assignment,) = await env.user_roles.get_by_tenant(TENANT)
    held = await env.roles.get_by_id(str(assignment.role_id))
    assert held is not None
    await env.roles.add_permission(str(held.id), str(read.id), str(own.id))

    with pytest.raises(EscalationRefused) as exc:
        await env.service(actor).create_role("Cashier", [ref(read)], None)
    assert exc.value.uncovered == [entry("invoices:read")]

    role = await env.service(actor).create_role("Cashier", [ref(read, own)], None)
    assert role.grants == [entry("invoices:read", "own")]


async def test_update_cannot_add_permission_the_manager_lacks(env: Env) -> None:
    read = await env.permission("invoices", "read")
    refund = await env.permission("refunds", "create")
    actor = await env.manager(holds=[read])
    role = await env.service(actor).create_role("Cashier", [ref(read)], None)

    with pytest.raises(EscalationRefused) as exc:
        await env.service(actor).update_role(role.id, None, [ref(read), ref(refund)])

    assert exc.value.uncovered == [entry("refunds:create")]
    stored = await env.roles.get_by_id(role.id)
    assert stored is not None
    assert len(stored.grants) == 1


async def test_developer_is_exempt_from_escalation(env: Env) -> None:
    refund = await env.permission("refunds", "create")

    role = await env.service().create_role("Refunder", [ref(refund)], None)

    assert role.grants == [entry("refunds:create")]


# --- assignable permissions --------------------------------------------------


async def test_unassignable_permission_refused(env: Env) -> None:
    secret = await env.permission("payroll", "read", assignable=False)
    other = await env.permission("ledger", "read", assignable=False)

    with pytest.raises(NotAssignable) as exc:
        await env.service().create_role("X", [ref(secret), ref(other)], None)

    assert exc.value.permissions == ["payroll:read", "ledger:read"]
    assert exc.value.details["reason"] == "not_assignable"
    assert isinstance(exc.value, ConflictError)


async def test_inactive_permission_refused(env: Env) -> None:
    gone = await env.permission("old", "read", active=False)

    with pytest.raises(NotAssignable) as exc:
        await env.service().create_role("X", [ref(gone)], None)

    assert exc.value.permissions == ["old:read"]


async def test_builtin_permission_refused(env: Env) -> None:
    manage = await env._manage_permission()
    manage.assignable = True  # even a mis-flagged built-in is refused

    with pytest.raises(NotAssignable) as exc:
        await env.service().create_role("X", [ref(manage)], None)

    assert exc.value.permissions == ["osiki.team:manage"]


@pytest.mark.parametrize("actor_kind", ["developer", "manager"])
async def test_resource_wildcard_permission_refused(env: Env, actor_kind: str) -> None:
    everything = await env.permission("*", "*")
    any_manage = await env.permission("*", "manage")
    actor = DEVELOPER if actor_kind == "developer" else await env.manager()

    with pytest.raises(NotAssignable) as exc:
        await env.service(actor).create_role(
            "X", [ref(everything), ref(any_manage)], None
        )

    assert exc.value.permissions == ["*:*", "*:manage"]


async def test_action_wildcard_permission_is_allowed(env: Env) -> None:
    every_invoice = await env.permission("invoices", "*")

    role = await env.service().create_role("X", [ref(every_invoice)], None)

    assert role.grants == [entry("invoices:*")]


async def test_same_permission_under_two_conditions_is_listed_once(env: Env) -> None:
    secret = await env.permission("payroll", "read", assignable=False)
    own = await env.condition("own")
    mine = await env.condition("mine")

    with pytest.raises(NotAssignable) as exc:
        await env.service().create_role(
            "X", [ref(secret, own), ref(secret, mine)], None
        )

    assert exc.value.permissions == ["payroll:read"]


async def test_references_are_validated_before_assignability(env: Env) -> None:
    secret = await env.permission("payroll", "read", assignable=False)

    with pytest.raises(ValidationError):
        await env.service().create_role(
            "X", [ref(secret), GrantRef(permission_id=str(PydanticObjectId()))], None
        )
    with pytest.raises(ValidationError):
        await env.service().create_role(
            "X", [GrantRef(permission_id="not-an-object-id"), ref(secret)], None
        )
    read = await env.permission("invoices", "read")
    with pytest.raises(ValidationError):
        await env.service().create_role(
            "X",
            [
                GrantRef(
                    permission_id=str(read.id), condition_id=str(PydanticObjectId())
                )
            ],
            None,
        )


async def test_references_are_validated_before_escalation(env: Env) -> None:
    actor = await env.manager()

    with pytest.raises(ValidationError):
        await env.service(actor).create_role(
            "X", [GrantRef(permission_id=str(PydanticObjectId()))], None
        )


async def test_duplicate_grants_are_stored_once(env: Env) -> None:
    read = await env.permission("invoices", "read")

    role = await env.service().create_role("X", [ref(read), ref(read)], None)

    assert role.grants == [entry("invoices:read")]


# --- templates ---------------------------------------------------------------


async def test_list_roles_offers_only_usable_templates_then_tenant_roles(
    env: Env,
) -> None:
    read = await env.permission("invoices", "read")
    secret = await env.permission("payroll", "read", assignable=False)
    manage = await env._manage_permission()
    owner = await env.template("Owner", [manage])
    cashier = await env.template("Cashier", [read])
    await env.template("Payroll", [read, secret])
    await env.template("Retired", [read], active=False)
    await env.roles.create(make_role("Not a template", permission_ids=[read.id]))
    mine = await env.service().create_role("Mine", [ref(read)], None)
    await env.roles.create(make_role("Theirs", tenant_id="globex"))

    roles = await env.service().list_roles()

    assert [(r.id, r.name, r.kind) for r in roles] == [
        (str(owner.id), "Owner", "template"),
        (str(cashier.id), "Cashier", "template"),
        (mine.id, "Mine", "tenant"),
    ]
    assert roles[0].grants == [entry("osiki.team:manage")]


async def test_template_with_missing_permission_is_not_offered(env: Env) -> None:
    ghost = make_role("Ghost", permission_ids=[PydanticObjectId()], is_template=True)
    await env.roles.create(ghost)

    assert await env.service().list_roles() == []


async def test_copy_from_unoffered_template_refused(env: Env) -> None:
    read = await env.permission("invoices", "read")
    secret = await env.permission("payroll", "read", assignable=False)
    template = await env.template("Payroll", [read, secret])

    with pytest.raises(NotOffered) as exc:
        await env.service().create_role("Mine", [ref(read)], str(template.id))

    assert exc.value.details["reason"] == "not_offered"
    assert isinstance(exc.value, ConflictError)


@pytest.mark.parametrize("copied_from", ["nope", None])
async def test_copy_from_unknown_or_non_template_refused(
    env: Env, copied_from: str | None
) -> None:
    read = await env.permission("invoices", "read")
    plain = await env.roles.create(make_role("Plain", permission_ids=[read.id]))

    with pytest.raises(NotOffered):
        await env.service().create_role(
            "Mine", [ref(read)], copied_from or str(plain.id)
        )
    with pytest.raises(NotOffered):
        await env.service().create_role("Mine", [ref(read)], str(PydanticObjectId()))


async def test_copy_records_copied_from(env: Env) -> None:
    read = await env.permission("invoices", "read")
    manage = await env._manage_permission()
    template = await env.template("Owner", [manage, read])

    role = await env.service().create_role("Boss", [ref(read)], str(template.id))

    assert role.copied_from == str(template.id)
    assert role.grants == [entry("invoices:read")]  # no osiki.* ever copied
    stored = await env.roles.get_by_id(role.id)
    assert stored is not None
    assert stored.copied_from == template.id


async def test_copying_an_offered_template_with_builtin_grant_cannot_smuggle_it(
    env: Env,
) -> None:
    manage = await env._manage_permission()
    template = await env.template("Owner", [manage])

    with pytest.raises(NotAssignable):
        await env.service().create_role("Boss", [ref(manage)], str(template.id))


# --- names ---------------------------------------------------------------------


async def test_same_name_allowed_in_other_tenant_and_as_project_role(
    env: Env,
) -> None:
    await env.roles.create(make_role("Cashier"))  # project role
    other = await env.service(tenant="globex").create_role("Cashier", [], None)
    mine = await env.service().create_role("Cashier", [], None)

    assert other.id != mine.id
    assert mine.name == "Cashier"


async def test_same_name_in_the_tenant_is_a_conflict(env: Env) -> None:
    await env.service().create_role("Cashier", [], None)

    with pytest.raises(ConflictError) as exc:
        await env.service().create_role("Cashier", [], None)

    assert exc.value.details == {"name": "Cashier"}


async def test_name_of_a_deleted_role_can_be_reused(env: Env) -> None:
    role = await env.service().create_role("Cashier", [], None)
    await env.service().delete_role(role.id)

    again = await env.service().create_role("Cashier", [], None)

    assert again.id != role.id
    stored = await env.roles.get_by_id(role.id)
    assert stored is not None
    assert (stored.is_active, stored.name) == (False, f"Cashier #deleted-{role.id}")
    logs = await env.audit_repo.list(TENANT, 0, 10)
    delete = next(log for log in logs if log.action == "role.delete")
    assert delete.changes.before is not None
    assert delete.changes.before["name"] == "Cashier"


async def test_rename_to_a_taken_name_is_a_conflict(env: Env) -> None:
    await env.service().create_role("Cashier", [], None)
    other = await env.service().create_role("Waiter", [], None)

    with pytest.raises(ConflictError):
        await env.service().update_role(other.id, "Cashier", None)

    stored = await env.roles.get_by_id(other.id)
    assert stored is not None
    assert stored.name == "Waiter"


async def test_rename_to_a_deleted_roles_name_succeeds(env: Env) -> None:
    gone = await env.service().create_role("Gone", [], None)
    await env.service().delete_role(gone.id)
    other = await env.service().create_role("Waiter", [], None)

    renamed = await env.service().update_role(other.id, "Gone", None)

    assert renamed.name == "Gone"


class _RacingRoles(MockRoleRepository):
    """Passes the name check, then loses the race on the unique index."""

    async def create(self, role, *, session=None):  # type: ignore[no-untyped-def]
        raise DuplicateKeyError("E11000")

    async def update(self, role, *, session=None):  # type: ignore[no-untyped-def]
        raise DuplicateKeyError("E11000")


async def test_losing_a_name_race_is_a_conflict(env: Env) -> None:
    existing = await env.service().create_role("Waiter", [], None)
    racing = _RacingRoles("default", env.state)
    racing._data = env.roles._data
    env.roles = racing

    with pytest.raises(ConflictError):
        await env.service().create_role("Cashier", [], None)
    with pytest.raises(ConflictError):
        await env.service().update_role(existing.id, "Till", None)
    stored = await env.roles.get_by_id(existing.id)
    assert stored is not None and stored.name == "Waiter"


async def test_rejected_update_leaves_the_stored_role_untouched(env: Env) -> None:
    read = await env.permission("invoices", "read")
    await env.service().create_role("Cashier", [], None)
    other = await env.service().create_role("Waiter", [], None)

    with pytest.raises(ConflictError):
        await env.service().update_role(other.id, "Cashier", [ref(read)])

    stored = await env.roles.get_by_id(other.id)
    assert stored is not None
    assert stored.grants == []


# --- update / delete ---------------------------------------------------------------


async def test_update_renames_and_replaces_grants(env: Env) -> None:
    read = await env.permission("invoices", "read")
    write = await env.permission("invoices", "write")
    role = await env.service().create_role("Cashier", [ref(read)], None)

    updated = await env.service().update_role(role.id, "Till", [ref(write)])

    assert (updated.name, updated.grants) == ("Till", [entry("invoices:write")])
    assert updated.id == role.id


async def test_update_to_the_same_name_is_allowed(env: Env) -> None:
    role = await env.service().create_role("Cashier", [], None)

    updated = await env.service().update_role(role.id, "Cashier", None)

    assert updated.name == "Cashier"


async def test_update_with_nothing_to_change_keeps_the_role(env: Env) -> None:
    read = await env.permission("invoices", "read")
    role = await env.service().create_role("Cashier", [ref(read)], None)

    updated = await env.service().update_role(role.id, None, None)

    assert (updated.name, updated.grants) == ("Cashier", [entry("invoices:read")])


@pytest.mark.parametrize("kind", ["project", "other_tenant", "deleted", "bad_id"])
async def test_only_this_tenants_active_roles_can_be_touched(
    env: Env, kind: str
) -> None:
    if kind == "project":
        role_id = str((await env.roles.create(make_role("Proj"))).id)
    elif kind == "other_tenant":
        role_id = (await env.service(tenant="globex").create_role("R", [], None)).id
    elif kind == "deleted":
        role_id = (await env.service().create_role("R", [], None)).id
        await env.service().delete_role(role_id)
    else:
        role_id = "not-an-object-id"

    with pytest.raises(NotFoundError):
        await env.service().update_role(role_id, "Z", None)
    with pytest.raises(NotFoundError):
        await env.service().delete_role(role_id)


async def test_malformed_role_id_is_not_found_not_an_invalid_id_crash(
    env: Env,
) -> None:
    class StrictRoles(MockRoleRepository):
        async def get_by_id(self, role_id, *, session=None):  # type: ignore[no-untyped-def]
            return await super().get_by_id(str(PydanticObjectId(role_id)))

    env.roles = StrictRoles("default", env.state)

    with pytest.raises(NotFoundError):
        await env.service().update_role("not-an-object-id", "Z", None)
    with pytest.raises(NotFoundError):
        await env.service().delete_role("not-an-object-id")


async def test_unknown_role_id_is_not_found(env: Env) -> None:
    with pytest.raises(NotFoundError):
        await env.service().delete_role(str(PydanticObjectId()))


async def test_delete_removes_the_role_from_listing(env: Env) -> None:
    role = await env.service().create_role("Cashier", [], None)

    await env.service().delete_role(role.id)

    assert await env.service().list_roles() == []
    stored = await env.roles.get_by_id(role.id)
    assert stored is not None and not stored.is_active


async def test_delete_refused_while_held(env: Env) -> None:
    role = await env.service().create_role("Cashier", [], None)
    user = await env.users.create(make_user(external_id="u1"))
    assert user.id is not None
    await env.user_roles.create(
        make_user_role(user.id, PydanticObjectId(role.id), Scope(tenant_id=TENANT))
    )

    with pytest.raises(RoleInUse) as exc:
        await env.service().delete_role(role.id)

    assert exc.value.details["reason"] == "role_in_use"
    assert isinstance(exc.value, ConflictError)
    stored = await env.roles.get_by_id(role.id)
    assert stored is not None and stored.is_active


async def test_delete_refused_while_a_group_holds_it(env: Env) -> None:
    role = await env.service().create_role("Cashier", [], None)
    group = await env.groups.create(make_group("staff"))
    assert group.id is not None
    await env.group_roles.create(
        make_group_role(group.id, PydanticObjectId(role.id), Scope(tenant_id=TENANT))
    )

    with pytest.raises(RoleInUse):
        await env.service().delete_role(role.id)


async def test_assignment_in_another_tenant_does_not_block_delete(env: Env) -> None:
    role = await env.service().create_role("Cashier", [], None)
    group = await env.groups.create(make_group("staff"))
    user = await env.users.create(make_user(external_id="u1"))
    assert group.id is not None and user.id is not None
    await env.group_roles.create(
        make_group_role(group.id, PydanticObjectId(role.id), Scope(tenant_id="globex"))
    )
    await env.user_roles.create(
        make_user_role(user.id, PydanticObjectId(role.id), Scope(tenant_id="globex"))
    )

    await env.service().delete_role(role.id)


async def test_revoked_assignment_does_not_block_delete(env: Env) -> None:
    role = await env.service().create_role("Cashier", [], None)
    user = await env.users.create(make_user(external_id="u1"))
    assert user.id is not None
    assignment = await env.user_roles.create(
        make_user_role(user.id, PydanticObjectId(role.id), Scope(tenant_id=TENANT))
    )
    await env.user_roles.revoke(str(assignment.id))

    await env.service().delete_role(role.id)


async def test_list_roles_counts_holders_in_this_tenant(env: Env) -> None:
    role = await env.service().create_role("Cashier", [], None)
    group = await env.groups.create(make_group("staff"))
    user = await env.users.create(make_user(external_id="u1"))
    assert group.id is not None and user.id is not None
    rid = PydanticObjectId(role.id)
    await env.user_roles.create(make_user_role(user.id, rid, Scope(tenant_id=TENANT)))
    await env.group_roles.create(
        make_group_role(group.id, rid, Scope(tenant_id=TENANT))
    )
    await env.group_roles.create(
        make_group_role(group.id, rid, Scope(tenant_id="globex"))
    )

    (listed,) = await env.service().list_roles()

    assert listed.holders == 2


# --- versions and audit ------------------------------------------------------------


async def test_each_write_bumps_assignments_version_not_config_version(
    env: Env,
) -> None:
    read = await env.permission("invoices", "read")
    config = await env.state.get_config_version()
    assignments = await env.state.get_assignments_version()
    service = env.service()

    role = await service.create_role("Cashier", [ref(read)], None)
    assert await env.state.get_assignments_version() == assignments + 1
    await service.update_role(role.id, "Till", None)
    assert await env.state.get_assignments_version() == assignments + 2
    await service.delete_role(role.id)
    assert await env.state.get_assignments_version() == assignments + 3

    assert await env.state.get_config_version() == config


async def test_each_write_records_one_audit_entry_with_tenant_and_actor(
    env: Env,
) -> None:
    read = await env.permission("invoices", "read")
    write = await env.permission("invoices", "write")
    own = await env.condition("own")
    actor = Actor(type="developer", id="dev-9")
    service = env.service(actor)

    role = await service.create_role("Cashier", [ref(read)], None)
    assert await env.audit_repo.count(TENANT) == 1
    await service.update_role(role.id, "Till", [ref(read), ref(write, own)])
    assert await env.audit_repo.count(TENANT) == 2
    await service.delete_role(role.id)
    assert await env.audit_repo.count(TENANT) == 3

    delete, update, create = await env.audit_repo.list(TENANT, 0, 10)
    for log, action in (
        (create, "role.create"),
        (update, "role.update"),
        (delete, "role.delete"),
    ):
        assert (log.action, log.target_type, log.target_id) == (action, "role", role.id)
        assert (log.tenant_id, log.actor_id, log.actor_type) == (
            TENANT,
            "dev-9",
            "developer",
        )
    assert create.changes.before is None
    assert create.changes.after == {"name": "Cashier", "permissions": ["invoices:read"]}
    assert update.changes.before == {
        "name": "Cashier",
        "permissions": ["invoices:read"],
    }
    assert update.changes.after == {
        "name": "Till",
        "permissions": ["invoices:read", "invoices:write@own"],
    }
    assert delete.changes.before == update.changes.after
    assert delete.changes.after is None


async def test_refused_writes_leave_no_audit_entry_or_version_bump(env: Env) -> None:
    secret = await env.permission("payroll", "read", assignable=False)
    before = await env.state.get_assignments_version()

    with pytest.raises(NotAssignable):
        await env.service().create_role("X", [ref(secret)], None)

    assert await env.audit_repo.count(None) == 0
    assert await env.state.get_assignments_version() == before


async def test_tenant_user_actor_is_recorded(env: Env) -> None:
    actor = await env.manager("boss")

    await env.service(actor).create_role("Cashier", [], None)

    (log,) = await env.audit_repo.list(TENANT, 0, 10)
    assert (log.actor_id, log.actor_type) == ("boss", "tenant_user")


# --- review focus 4 ----------------------------------------------------------------


async def test_unmarked_permission_existing_role_keeps_working_but_edit_must_drop_it(
    env: Env,
) -> None:
    read = await env.permission("invoices", "read")
    keep = await env.permission("invoices", "write")
    role = await env.service().create_role("Cashier", [ref(read), ref(keep)], None)
    user = await env.users.create(make_user(external_id="till-1"))
    await env.tenants.upsert(TENANT, TENANT, {})
    await env.members.add(TENANT, "till-1")
    assert user.id is not None
    await env.user_roles.create(
        make_user_role(user.id, PydanticObjectId(role.id), Scope(tenant_id=TENANT))
    )

    read.assignable = False  # the developer flips it off
    await env.permissions.update(read)

    (listed,) = await env.service().list_roles()
    assert entry("invoices:read") in listed.grants
    bundle = await env.service()._bundle_builder.build("till-1")
    assert bundle is not None
    assert "invoices:read" in {g.permission for r in bundle.roles for g in r.grants}

    with pytest.raises(NotAssignable) as exc:
        await env.service().update_role(role.id, None, [ref(read), ref(keep)])
    assert exc.value.permissions == ["invoices:read"]

    # a rename alone leaves the grant in place; dropping it succeeds
    await env.service().update_role(role.id, "Till", None)
    updated = await env.service().update_role(role.id, None, [ref(keep)])
    assert updated.grants == [entry("invoices:write")]


async def test_expired_assignment_does_not_block_delete_or_count(env: Env) -> None:
    role = await env.service().create_role("Cashier", [], None)
    user = await env.users.create(make_user(external_id="u1"))
    group = await env.groups.create(make_group("staff"))
    assert user.id is not None and group.id is not None
    rid = PydanticObjectId(role.id)
    scope = Scope(tenant_id=TENANT)
    direct = await env.user_roles.create(make_user_role(user.id, rid, scope))
    grouped = await env.group_roles.create(make_group_role(group.id, rid, scope))
    direct.expires_at = time.time() - 5
    grouped.expires_at = time.time() - 5

    (listed,) = await env.service().list_roles()
    assert listed.holders == 0
    await env.service().delete_role(role.id)


async def test_unexpired_assignment_with_future_expiry_still_blocks_delete(
    env: Env,
) -> None:
    role = await env.service().create_role("Cashier", [], None)
    user = await env.users.create(make_user(external_id="u1"))
    assert user.id is not None
    await env.user_roles.create(
        make_user_role(
            user.id,
            PydanticObjectId(role.id),
            Scope(tenant_id=TENANT),
            expires_at=time.time() + 3600,
        )
    )

    with pytest.raises(RoleInUse):
        await env.service().delete_role(role.id)


async def test_template_with_inactive_assignable_permission_is_not_offered(
    env: Env,
) -> None:
    dead = await env.permission("old", "read", assignable=True, active=False)
    await env.template("Dead", [dead])

    assert await env.service().list_roles() == []


async def test_update_that_changes_nothing_skips_write_bump_and_audit(
    env: Env,
) -> None:
    read = await env.permission("invoices", "read")
    role = await env.service().create_role("Cashier", [ref(read)], None)
    version = await env.state.get_assignments_version()
    logs = await env.audit_repo.count(None)

    same = await env.service().update_role(role.id, None, None)
    renamed_to_itself = await env.service().update_role(role.id, "Cashier", None)

    assert same == renamed_to_itself == role
    assert await env.state.get_assignments_version() == version
    assert await env.audit_repo.count(None) == logs


async def test_failed_rename_does_not_touch_the_stored_role(env: Env) -> None:
    await env.service().create_role("Cashier", [], None)
    other = await env.service().create_role("Waiter", [], None)
    stored = await env.roles.get_by_id(other.id)

    with pytest.raises(ConflictError):
        await env.service().update_role(other.id, "Cashier", None)

    assert stored is not None and stored.name == "Waiter"


# --- models ------------------------------------------------------------------------


def test_team_error_shapes() -> None:
    assert NotManager().details == {"reason": "not_manager"}
    assert LastManager().details == {"reason": "last_manager"}
    assert isinstance(LastManager(), ConflictError)
    refused = EscalationRefused([entry("a:b", "own"), entry("c:d")])
    assert refused.details["uncovered"] == "a:b@own, c:d"
    assert NotOffered("r1").details == {"reason": "not_offered", "role_id": "r1"}
    assert RoleInUse("r1").details == {"reason": "role_in_use", "role_id": "r1"}


def test_team_role_defaults() -> None:
    role = TeamRole(id="1", name="n", kind="tenant", grants=[])
    assert (role.copied_from, role.holders) == (None, 0)
