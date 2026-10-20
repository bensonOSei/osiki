"""TeamService: members, assignments, the last-manager guard, effective view,
and the dry run."""

import time
from typing import Any

import pytest
from beanie import PydanticObjectId
from pymongo.errors import DuplicateKeyError

from osiki.api.actor import Actor
from osiki.api.exceptions import ConflictError, NotFoundError
from osiki.models.base import Scope
from osiki.models.constraint import ConstraintConfig, ConstraintType, ScopeLevel
from osiki.models.permission import Permission
from osiki.models.role import Role
from osiki.models.user import User
from osiki.models.user_role import UserRole
from osiki.services.builtins import ensure_builtins
from osiki.services.team.models import (
    ConstraintViolated,
    EffectiveSource,
    EscalationRefused,
    LastManager,
    NotManager,
    NotOffered,
    TeamMember,
    TeamRoleRef,
    Violation,
)
from tests.mocks import (
    make_constraint,
    make_group,
    make_group_role,
    make_role,
    make_snapshot,
    make_user,
    make_user_group,
    make_user_role,
)
from tests.unit.services.team.test_team_roles import DEVELOPER, TENANT, Env, ref


@pytest.fixture
def env() -> Env:
    return Env()


async def owner_role(env: Env) -> Role:
    builtins = await ensure_builtins(env.permissions, env.roles)
    role = await env.roles.get_by_id(builtins.owner_role_id)
    assert role is not None
    return role


async def tenant_role(
    env: Env, name: str, permissions: list[Permission], tenant: str = TENANT
) -> Role:
    return await env.roles.create(
        make_role(
            name, permission_ids=[p.id for p in permissions if p.id], tenant_id=tenant
        )
    )


async def member(
    env: Env,
    external_id: str,
    roles: list[Role] | None = None,
    *,
    expires_at: float | None = None,
    tenant: str = TENANT,
) -> User:
    """A tenant member holding ``roles`` directly, scoped to the tenant."""
    user = await env.users.create(make_user(external_id=external_id))
    await env.tenants.upsert(tenant, tenant, {})
    await env.members.add(tenant, external_id)
    for role in roles or []:
        assert user.id is not None and role.id is not None
        await env.user_roles.create(
            make_user_role(
                user.id, role.id, scope=Scope(tenant_id=tenant), expires_at=expires_at
            )
        )
    return user


async def owner(env: Env, external_id: str, **kwargs: Any) -> Actor:
    await member(env, external_id, [await owner_role(env)], **kwargs)
    return Actor(type="tenant_user", id=external_id)


async def group_owner(env: Env, external_id: str) -> None:
    """A member who holds Owner only through a group scoped to the tenant."""
    user = await member(env, external_id)
    group = await env.groups.create(make_group(f"group-{external_id}"))
    owner_id = (await owner_role(env)).id
    assert user.id is not None and group.id is not None and owner_id is not None
    await env.user_groups.create(make_user_group(user.id, group.id))
    await env.group_roles.create(
        make_group_role(group.id, owner_id, scope=Scope(tenant_id=TENANT))
    )


async def active_assignment(env: Env, external_id: str, role: Role) -> UserRole | None:
    user = await env.users.get_by_external_id(external_id)
    assert user is not None
    return await env.user_roles.find_assignment(str(user.id), str(role.id), TENANT)


async def audit_actions(env: Env) -> list[str]:
    return [e.action for e in await env.audit_repo.list(None, 0, 100)]


# -- add_member --------------------------------------------------------------


async def test_add_member_creates_user_membership_assignment_and_one_audit_entry(
    env: Env,
) -> None:
    cashier = await tenant_role(env, "Cashier", [await env.permission("till", "open")])
    await env.tenants.upsert(TENANT, TENANT, {})
    version = await env.state.get_assignments_version()

    result = await env.service().add_member(
        "u-new", name="Ama", email="ama@example.com", role_id=str(cashier.id)
    )

    assert result == TeamMember(
        user_id="u-new",
        name="Ama",
        email="ama@example.com",
        roles=[TeamRoleRef(id=str(cashier.id), name="Cashier", kind="tenant")],
    )
    user = await env.users.get_by_external_id("u-new")
    assert user is not None and user.email == "ama@example.com"
    assert await env.members.is_member(TENANT, "u-new")
    assignment = await active_assignment(env, "u-new", cashier)
    assert assignment is not None and assignment.assigned_by == "developer:dev-1"
    assert assignment.scope.to_dict() == {"tenant_id": TENANT}
    assert await env.state.get_assignments_version() > version
    entries = await env.audit_repo.list(None, 0, 10)
    assert [(e.action, e.target_type, e.target_id, e.tenant_id) for e in entries] == [
        ("member.add", "member", "u-new", TENANT)
    ]
    assert entries[0].changes.after == {"user_id": "u-new", "roles": ["Cashier"]}
    assert env.locks._data[TENANT].version == 1


async def test_non_manager_cannot_hand_on_owner(env: Env) -> None:
    """A tenant_user who does not hold ``osiki.team:manage`` (only Cashier) is
    refused before any assignment rule runs, so they can never hand on Owner."""
    cashier = await tenant_role(env, "Cashier", [await env.permission("till", "open")])
    await member(env, "cashier", [cashier])
    owner_id = str((await owner_role(env)).id)
    service = env.service(Actor(type="tenant_user", id="cashier"))

    with pytest.raises(NotManager):
        await service.add_member("u-new", name=None, email=None, role_id=owner_id)
    assert await env.users.get_by_external_id("u-new") is None
    assert TENANT not in env.locks._data


async def test_add_member_with_a_role_whose_grants_are_not_held_is_escalation(
    env: Env,
) -> None:
    read = await env.permission("invoices", "read")
    write = await env.permission("invoices", "write")
    actor = await env.manager(holds=[read])
    writer = await tenant_role(env, "Writer", [write])

    with pytest.raises(EscalationRefused) as caught:
        await env.service(actor).add_member(
            "u-new", name=None, email=None, role_id=str(writer.id)
        )
    assert caught.value.details["uncovered"] == "invoices:write"
    assert await env.users.get_by_external_id("u-new") is None
    assert await audit_actions(env) == []


async def test_assigning_a_template_checks_its_inherited_grants(env: Env) -> None:
    read = await env.permission("invoices", "read")
    write = await env.permission("invoices", "write")
    actor = await env.manager(holds=[read])
    parent = await env.roles.create(make_role("Parent", permission_ids=[write.id]))
    child = await env.roles.create(
        make_role(
            "Child",
            permission_ids=[read.id],
            parent_role_id=parent.id,
            is_template=True,
        )
    )

    with pytest.raises(EscalationRefused) as caught:
        await env.service(actor).add_member(
            "u-new", name=None, email=None, role_id=str(child.id)
        )
    assert caught.value.details["uncovered"] == "invoices:write"


async def test_owner_can_hand_on_management(env: Env) -> None:
    actor = await owner(env, "boss")
    owner_id = str((await owner_role(env)).id)

    result = await env.service(actor).add_member(
        "deputy", name="Kofi", email=None, role_id=owner_id
    )

    assert result.roles == [TeamRoleRef(id=owner_id, name="Owner", kind="template")]
    # The deputy now manages the team in their own right.
    await env.service(Actor(type="tenant_user", id="deputy")).require_manager()


async def test_add_member_of_an_existing_member_adds_the_role(env: Env) -> None:
    till = await env.permission("till", "open")
    cashier = await tenant_role(env, "Cashier", [till])
    stock = await tenant_role(env, "Stock", [await env.permission("stock", "count")])
    await member(env, "u-1", [cashier])

    result = await env.service().add_member(
        "u-1", name=None, email=None, role_id=str(stock.id)
    )

    assert {r.name for r in result.roles} == {"Cashier", "Stock"}


async def test_add_member_refuses_an_email_another_user_has(env: Env) -> None:
    cashier = await tenant_role(env, "Cashier", [await env.permission("till", "open")])
    taken = make_user(external_id="other")
    taken.email = "ama@example.com"
    await env.users.create(taken)

    with pytest.raises(ConflictError) as caught:
        await env.service().add_member(
            "u-new", name=None, email="ama@example.com", role_id=str(cashier.id)
        )
    assert caught.value.details == {"email": "ama@example.com"}
    assert await env.users.get_by_external_id("u-new") is None


async def test_add_member_maps_an_email_race_to_conflict(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    cashier = await tenant_role(env, "Cashier", [await env.permission("till", "open")])

    async def collide(*args: object, **kwargs: object) -> User:
        raise DuplicateKeyError("email")

    monkeypatch.setattr(env.users, "create", collide)
    with pytest.raises(ConflictError) as caught:
        await env.service().add_member(
            "u-new", name=None, email=None, role_id=str(cashier.id)
        )
    assert caught.value.details == {"email": ""}


async def test_add_member_uses_the_user_a_concurrent_add_created(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    cashier = await tenant_role(env, "Cashier", [await env.permission("till", "open")])
    racer = make_user(external_id="u-new")
    racer.name = "Racer"
    real_create = env.users.create

    async def lose_the_race(user: User, **kwargs: Any) -> User:
        await real_create(racer)
        raise DuplicateKeyError("external_id")

    monkeypatch.setattr(env.users, "create", lose_the_race)
    result = await env.service().add_member(
        "u-new", name="Mine", email=None, role_id=str(cashier.id)
    )
    assert result.name == "Racer"
    assert await active_assignment(env, "u-new", cashier) is not None


async def test_add_member_does_not_overwrite_an_existing_users_profile(
    env: Env,
) -> None:
    """Users are environment-wide: adding tenant B's user to tenant A must not
    rewrite their name or email (ruling M3A-15)."""
    cashier = await tenant_role(env, "Cashier", [await env.permission("till", "open")])
    theirs = make_user(external_id="shared")
    theirs.name, theirs.email = "Abena", "abena@b.example"
    await env.users.create(theirs)
    await env.members.add("tenant-b", "shared")
    taken = make_user(external_id="other")
    taken.email = "taken@example.com"
    await env.users.create(taken)
    version = await env.state.get_assignments_version()

    # Even an email another user holds is ignored rather than refused.
    result = await env.service().add_member(
        "shared", name="Hijack", email="taken@example.com", role_id=str(cashier.id)
    )

    stored = await env.users.get_by_external_id("shared")
    assert stored is not None
    assert (stored.name, stored.email) == ("Abena", "abena@b.example")
    assert (result.name, result.email) == ("Abena", "abena@b.example")
    assert await env.members.is_member(TENANT, "shared")
    # Membership and assignment bump the version; no user write does.
    assert await env.state.get_assignments_version() == version + 2


# -- which roles may be assigned ---------------------------------------------


@pytest.mark.parametrize("role_id", ["not-an-id", str(PydanticObjectId())])
async def test_assigning_an_unknown_role_is_not_found(env: Env, role_id: str) -> None:
    await member(env, "u-1")
    with pytest.raises(NotFoundError) as caught:
        await env.service().assign_role("u-1", role_id)
    assert caught.value.details == {"role_id": role_id}


async def test_assigning_an_inactive_role_is_not_found(env: Env) -> None:
    await member(env, "u-1")
    gone = await env.roles.create(make_role("Gone", tenant_id=TENANT, is_active=False))
    with pytest.raises(NotFoundError):
        await env.service().assign_role("u-1", str(gone.id))


async def test_assigning_another_tenants_role_is_not_found(env: Env) -> None:
    """Tenant isolation: the bundle ships any referenced tenant role, so a
    foreign role id must never be assignable here."""
    await member(env, "u-1")
    foreign = await tenant_role(
        env, "Theirs", [await env.permission("till", "open")], tenant="other"
    )
    with pytest.raises(NotFoundError):
        await env.service().assign_role("u-1", str(foreign.id))
    assert await active_assignment(env, "u-1", foreign) is None


async def test_assigning_a_project_role_that_is_not_a_template_is_not_offered(
    env: Env,
) -> None:
    await member(env, "u-1")
    project = await env.roles.create(
        make_role("Admin", permission_ids=[(await env.permission("till", "open")).id])
    )
    with pytest.raises(NotOffered):
        await env.service().assign_role("u-1", str(project.id))


async def test_assigning_a_template_that_is_not_offered_is_not_offered(
    env: Env,
) -> None:
    await member(env, "u-1")
    hidden = await env.template(
        "Hidden", [await env.permission("vault", "open", assignable=False)]
    )
    with pytest.raises(NotOffered):
        await env.service().assign_role("u-1", str(hidden.id))


# -- assign_role -------------------------------------------------------------


async def test_assign_role_assigns_and_audits(env: Env) -> None:
    cashier = await tenant_role(env, "Cashier", [await env.permission("till", "open")])
    await member(env, "u-1")

    result = await env.service().assign_role("u-1", str(cashier.id))

    assert [r.name for r in result.roles] == ["Cashier"]
    assignment = await active_assignment(env, "u-1", cashier)
    assert assignment is not None
    entries = await env.audit_repo.list(None, 0, 10)
    assert [(e.action, e.target_type, e.target_id) for e in entries] == [
        ("assignment.create", "assignment", str(assignment.id))
    ]
    assert entries[0].changes.after == {
        "user_id": "u-1",
        "role_id": str(cashier.id),
        "role": "Cashier",
    }


async def test_assign_role_to_a_non_member_is_not_found(env: Env) -> None:
    cashier = await tenant_role(env, "Cashier", [await env.permission("till", "open")])
    await env.users.create(make_user(external_id="outsider"))
    with pytest.raises(NotFoundError) as caught:
        await env.service().assign_role("outsider", str(cashier.id))
    assert caught.value.details == {"user_id": "outsider"}


async def test_assign_role_to_an_unknown_user_is_not_found(env: Env) -> None:
    cashier = await tenant_role(env, "Cashier", [await env.permission("till", "open")])
    with pytest.raises(NotFoundError) as caught:
        await env.service().assign_role("ghost", str(cashier.id))
    assert caught.value.details == {"user_id": "ghost"}


async def test_assigning_a_held_role_again_is_a_conflict(env: Env) -> None:
    cashier = await tenant_role(env, "Cashier", [await env.permission("till", "open")])
    await member(env, "u-1", [cashier])
    with pytest.raises(ConflictError) as caught:
        await env.service().assign_role("u-1", str(cashier.id))
    assert caught.value.details == {"user_id": "u-1", "role_id": str(cashier.id)}


async def test_an_expired_assignment_is_replaced(env: Env) -> None:
    cashier = await tenant_role(env, "Cashier", [await env.permission("till", "open")])
    await member(env, "u-1", [cashier], expires_at=time.time() - 60)
    expired = await active_assignment(env, "u-1", cashier)
    assert expired is not None

    await env.service().assign_role("u-1", str(cashier.id))

    assert not env.user_roles._data[str(expired.id)].is_active
    fresh = await active_assignment(env, "u-1", cashier)
    assert fresh is not None and fresh.id != expired.id and fresh.expires_at is None


async def test_a_concurrent_duplicate_assignment_is_a_conflict(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    cashier = await tenant_role(env, "Cashier", [await env.permission("till", "open")])
    await member(env, "u-1")

    async def collide(*args: object, **kwargs: object) -> UserRole:
        raise DuplicateKeyError("user_role")

    monkeypatch.setattr(env.user_roles, "create", collide)
    with pytest.raises(ConflictError) as caught:
        await env.service().assign_role("u-1", str(cashier.id))
    assert caught.value.details == {"user_id": "u-1", "role_id": str(cashier.id)}


async def test_a_constraint_violation_refuses_the_assignment(env: Env) -> None:
    cashier = await tenant_role(env, "Cashier", [await env.permission("till", "open")])
    await member(env, "u-1")
    await env.constraints.create(
        make_constraint(
            "one-cashier",
            ConstraintType.CARDINALITY,
            ConstraintConfig(
                role_id=cashier.id,
                max_assignments=0,
                scope_level=ScopeLevel.PER_TENANT,
            ),
        )
    )
    with pytest.raises(ConstraintViolated) as caught:
        await env.service().assign_role("u-1", str(cashier.id))
    assert caught.value.details["reason"] == "constraint"
    assert caught.value.details["constraint"] == "one-cashier"
    assert await active_assignment(env, "u-1", cashier) is None


# -- revoke_role, remove_member and the last-manager guard -------------------


async def test_revoking_last_manager_refused(env: Env) -> None:
    actor = await owner(env, "boss")
    owner_id = str((await owner_role(env)).id)

    with pytest.raises(LastManager) as caught:
        await env.service(actor).revoke_role("boss", owner_id)
    assert caught.value.details == {"reason": "last_manager"}
    assert await active_assignment(env, "boss", await owner_role(env)) is not None
    assert await audit_actions(env) == []


async def test_removing_last_manager_refused(env: Env) -> None:
    await owner(env, "boss")
    with pytest.raises(LastManager):
        await env.service().remove_member("boss")
    assert await env.members.is_member(TENANT, "boss")
    assert await active_assignment(env, "boss", await owner_role(env)) is not None
    assert await audit_actions(env) == []


async def test_second_manager_can_be_removed_when_one_remains(env: Env) -> None:
    actor = await owner(env, "boss")
    await owner(env, "deputy")
    owner_ = await owner_role(env)
    until = await active_assignment(env, "deputy", owner_)
    assert until is not None

    await env.service(actor).remove_member("deputy")

    assert not await env.members.is_member(TENANT, "deputy")
    assert await active_assignment(env, "deputy", owner_) is None
    entries = await env.audit_repo.list(None, 0, 10)
    assert [(e.action, e.target_id) for e in entries] == [("member.remove", "deputy")]
    assert entries[0].changes.before == {"user_id": "deputy", "roles": ["Owner"]}


async def test_second_manager_can_be_revoked_when_one_remains(env: Env) -> None:
    actor = await owner(env, "boss")
    await owner(env, "deputy")
    owner_ = await owner_role(env)

    await env.service(actor).revoke_role("deputy", str(owner_.id))

    assert await active_assignment(env, "deputy", owner_) is None
    entries = await env.audit_repo.list(None, 0, 10)
    assert [e.action for e in entries] == ["assignment.revoke"]
    assert entries[0].changes.before == {
        "user_id": "deputy",
        "role_id": str(owner_.id),
        "role": "Owner",
    }


async def test_a_manager_may_revoke_their_own_role_when_another_remains(
    env: Env,
) -> None:
    actor = await owner(env, "boss")
    await owner(env, "deputy")
    await env.service(actor).revoke_role("boss", str((await owner_role(env)).id))
    assert await active_assignment(env, "boss", await owner_role(env)) is None


async def test_group_held_manage_counts_for_guard(env: Env) -> None:
    await group_owner(env, "via-group")
    await owner(env, "boss")
    await env.service().revoke_role("boss", str((await owner_role(env)).id))
    assert await active_assignment(env, "boss", await owner_role(env)) is None


async def test_expired_manage_assignment_does_not_count(env: Env) -> None:
    await owner(env, "lapsed", expires_at=time.time() - 60)
    await owner(env, "boss")
    with pytest.raises(LastManager):
        await env.service().revoke_role("boss", str((await owner_role(env)).id))


async def test_manage_in_another_tenant_does_not_count(env: Env) -> None:
    await owner(env, "elsewhere", tenant="other")
    # A member here, but managing only the other tenant.
    await env.members.add(TENANT, "elsewhere")
    await owner(env, "boss")
    with pytest.raises(LastManager):
        await env.service().revoke_role("boss", str((await owner_role(env)).id))


async def test_revoking_another_role_of_the_last_manager_is_allowed(
    env: Env,
) -> None:
    cashier = await tenant_role(env, "Cashier", [await env.permission("till", "open")])
    await member(env, "boss", [await owner_role(env), cashier])
    await env.service().revoke_role("boss", str(cashier.id))
    assert await active_assignment(env, "boss", cashier) is None


async def test_a_member_without_a_user_record_never_counts(env: Env) -> None:
    await env.members.add(TENANT, "ghost")
    await owner(env, "boss")
    with pytest.raises(LastManager):
        await env.service().remove_member("boss")


async def test_the_guard_finds_a_manager_past_the_first_page(env: Env) -> None:
    await owner(env, "boss")
    for i in range(100):
        await env.members.add(TENANT, f"staff-{i:03}")
    await owner(env, "deputy")  # the 102nd member, on the second page
    await env.service().remove_member("boss")
    assert not await env.members.is_member(TENANT, "boss")


async def test_revoking_an_unassigned_role_is_not_found(env: Env) -> None:
    await owner(env, "boss")
    cashier = await tenant_role(env, "Cashier", [await env.permission("till", "open")])
    for role_id in [str(cashier.id), "not-an-id"]:
        with pytest.raises(NotFoundError) as caught:
            await env.service().revoke_role("boss", role_id)
        assert caught.value.details == {"user_id": "boss", "role_id": role_id}


async def test_removing_a_non_member_is_not_found(env: Env) -> None:
    await env.users.create(make_user(external_id="outsider"))
    with pytest.raises(NotFoundError) as caught:
        await env.service().remove_member("outsider")
    assert caught.value.details == {"user_id": "outsider"}


async def test_remove_member_revokes_only_the_members_assignments_here(
    env: Env,
) -> None:
    await owner(env, "boss")
    cashier = await tenant_role(env, "Cashier", [await env.permission("till", "open")])
    user = await member(env, "u-1", [cashier])
    theirs = await tenant_role(
        env, "Theirs", [await env.permission("till", "close")], tenant="other"
    )
    assert user.id is not None and theirs.id is not None
    elsewhere = await env.user_roles.create(
        make_user_role(user.id, theirs.id, scope=Scope(tenant_id="other"))
    )

    await env.service().remove_member("u-1")

    assert await active_assignment(env, "u-1", cashier) is None
    assert env.user_roles._data[str(elsewhere.id)].is_active
    # Other members' assignments in this tenant are untouched.
    assert await active_assignment(env, "boss", await owner_role(env)) is not None


async def test_removing_a_member_without_a_user_record_drops_the_membership(
    env: Env,
) -> None:
    await owner(env, "boss")
    await env.members.add(TENANT, "ghost")
    await env.service().remove_member("ghost")
    assert not await env.members.is_member(TENANT, "ghost")
    entries = await env.audit_repo.list(None, 0, 10)
    assert entries[0].changes.before == {"user_id": "ghost", "roles": []}


async def test_member_writes_require_a_manager_before_anything_is_written(
    env: Env,
) -> None:
    await owner(env, "boss")
    await member(env, "staff")
    service = env.service(Actor(type="tenant_user", id="staff"))
    with pytest.raises(NotManager):
        await service.remove_member("boss")
    with pytest.raises(NotManager):
        await service.revoke_role("boss", str((await owner_role(env)).id))
    assert TENANT not in env.locks._data


# -- list_members and effective ----------------------------------------------


async def test_list_members_shows_live_direct_roles(env: Env) -> None:
    cashier = await tenant_role(env, "Cashier", [await env.permission("till", "open")])
    stock = await tenant_role(env, "Stock", [await env.permission("stock", "count")])
    actor = await owner(env, "boss")
    await member(env, "u-1", [cashier])
    await member(env, "u-2", [stock], expires_at=time.time() - 60)
    await env.members.add(TENANT, "ghost")

    members = await env.service(actor).list_members()

    owner_id = str((await owner_role(env)).id)
    assert members == [
        TeamMember(
            user_id="boss",
            name=None,
            email=None,
            roles=[TeamRoleRef(id=owner_id, name="Owner", kind="template")],
        ),
        TeamMember(
            user_id="u-1",
            name=None,
            email=None,
            roles=[TeamRoleRef(id=str(cashier.id), name="Cashier", kind="tenant")],
        ),
        TeamMember(user_id="u-2", name=None, email=None, roles=[]),
        TeamMember(user_id="ghost", name=None, email=None, roles=[]),
    ]
    page = await env.service(actor).list_members(skip=1, limit=1)
    assert [m.user_id for m in page] == ["u-1"]


async def test_list_members_requires_a_manager(env: Env) -> None:
    await member(env, "staff")
    with pytest.raises(NotManager):
        await env.service(Actor(type="tenant_user", id="staff")).list_members()


async def test_effective_lists_role_sources(env: Env) -> None:
    till = await env.permission("till", "open")
    cashier = await tenant_role(env, "Cashier", [till])
    owner_ = await owner_role(env)
    user = await member(env, "u-1", [cashier, owner_])
    # Also via a group, and once more project-wide: same grant, same source.
    group = await env.groups.create(make_group("floor"))
    assert user.id is not None and group.id is not None and owner_.id is not None
    await env.user_groups.create(make_user_group(user.id, group.id))
    await env.group_roles.create(
        make_group_role(group.id, cashier.id, scope=Scope(tenant_id=TENANT))  # type: ignore[arg-type]
    )
    await env.user_roles.create(make_user_role(user.id, owner_.id))

    sources = await env.service().effective("u-1")

    assert sources == [
        EffectiveSource(
            permission="till:open",
            condition=None,
            role_id=str(cashier.id),
            role_name="Cashier",
            via="direct",
        ),
        EffectiveSource(
            permission="osiki.team:manage",
            condition=None,
            role_id=str(owner_.id),
            role_name="Owner",
            via="direct",
        ),
        EffectiveSource(
            permission="till:open",
            condition=None,
            role_id=str(cashier.id),
            role_name="Cashier",
            via="group",
        ),
    ]


async def test_effective_attributes_inherited_grants_to_the_ancestor(
    env: Env,
) -> None:
    read = await env.permission("invoices", "read")
    write = await env.permission("invoices", "write")
    parent = await env.roles.create(make_role("Parent", permission_ids=[write.id]))
    child = await env.roles.create(
        make_role("Child", permission_ids=[read.id], parent_role_id=parent.id)
    )
    await member(env, "u-1", [child])

    sources = await env.service().effective("u-1")

    assert [(s.permission, s.role_name) for s in sources] == [
        ("invoices:read", "Child"),
        ("invoices:write", "Parent"),
    ]


async def test_effective_skips_expired_foreign_and_missing_roles(env: Env) -> None:
    till = await env.permission("till", "open")
    cashier = await tenant_role(env, "Cashier", [till])
    user = await member(env, "u-1", [cashier], expires_at=time.time() - 60)
    theirs = await tenant_role(env, "Theirs", [till], tenant="other")
    gone = await env.roles.create(make_role("Gone", is_active=False))
    assert user.id is not None and theirs.id is not None and gone.id is not None
    await env.user_roles.create(
        make_user_role(user.id, theirs.id, scope=Scope(tenant_id="other"))
    )
    await env.user_roles.create(
        make_user_role(user.id, gone.id, scope=Scope(tenant_id=TENANT))
    )

    assert await env.service().effective("u-1") == []


async def test_effective_of_a_cyclic_hierarchy_stops(env: Env) -> None:
    read = await env.permission("invoices", "read")
    a_id, b_id = PydanticObjectId(), PydanticObjectId()
    await env.roles.create(
        make_role("A", permission_ids=[read.id], role_id=a_id, parent_role_id=b_id)
    )
    await env.roles.create(make_role("B", role_id=b_id, parent_role_id=a_id))
    await member(env, "u-1", [await env.roles.get_by_id(str(a_id))])  # type: ignore[list-item]
    sources = await env.service().effective("u-1")
    assert [s.role_name for s in sources] == ["A"]


async def test_effective_of_a_non_member_is_not_found(env: Env) -> None:
    await env.users.create(make_user(external_id="outsider"))
    with pytest.raises(NotFoundError):
        await env.service().effective("outsider")


async def test_effective_of_a_member_without_a_user_record_is_empty(env: Env) -> None:
    await env.members.add(TENANT, "ghost")
    assert await env.service().effective("ghost") == []


# -- validate (dry run) ------------------------------------------------------


async def snapshot_of_writes(env: Env) -> tuple[Any, ...]:
    return (
        await env.state.get_assignments_version(),
        await env.state.get_config_version(),
        len(await env.audit_repo.list(None, 0, 100)),
        dict(env.locks._data),
        len(env.users._data),
        len(env.user_roles._data),
        len(env.members._data),
        len(env.roles._data),
    )


async def test_validate_returns_violations_without_writing(env: Env) -> None:
    read = await env.permission("invoices", "read")
    write = await env.permission("invoices", "write")
    vault = await env.permission("vault", "open", assignable=False)
    actor = await env.manager(holds=[read])
    writer = await tenant_role(env, "Writer", [write])
    project = await env.roles.create(make_role("Admin", permission_ids=[read.id]))
    reader = await tenant_role(env, "Reader", [read])
    await member(env, "u-1")
    await env.constraints.create(
        make_constraint(
            "no-readers",
            ConstraintType.CARDINALITY,
            ConstraintConfig(
                role_id=reader.id,
                max_assignments=0,
                scope_level=ScopeLevel.PER_TENANT,
            ),
        )
    )
    service = env.service(actor)
    before = await snapshot_of_writes(env)

    # add_member for a user who does not exist yet: checked, not created.
    assert await service.validate(
        "add_member", user_id="invitee", name="Ama", email=None, role_id=str(writer.id)
    ) == [
        Violation(
            kind="escalation",
            message="Cannot grant permissions you do not hold",
            details={"reason": "escalation", "uncovered": "invoices:write"},
        )
    ]
    kinds = [
        (await service.validate("assign_role", user_id="u-1", role_id=str(project.id)))[
            0
        ].kind,
        (await service.validate("assign_role", user_id="u-1", role_id=str(reader.id)))[
            0
        ].kind,
        (
            await service.validate(
                "create_role", name="Vault", grants=[ref(vault)], copied_from=None
            )
        )[0].kind,
        (
            await service.validate(
                "update_role", role_id=str(reader.id), name=None, grants=[ref(write)]
            )
        )[0].kind,
        (await service.validate("remove_member", user_id="mgr"))[0].kind,
        (
            await service.validate(
                "revoke_role",
                user_id="mgr",
                role_id=str((await env.roles.get_by_name("held-by-mgr")).id),  # type: ignore[union-attr]
            )
        )[0].kind,
    ]
    assert kinds == [
        "not_offered",
        "constraint",
        "not_assignable",
        "escalation",
        "last_manager",
        "last_manager",
    ]
    assert await snapshot_of_writes(env) == before
    assert await env.users.get_by_external_id("invitee") is None


async def test_validate_returns_nothing_when_the_operation_would_pass(
    env: Env,
) -> None:
    read = await env.permission("invoices", "read")
    actor = await env.manager(holds=[read])
    reader = await tenant_role(env, "Reader", [read])
    service = env.service(actor)
    before = await snapshot_of_writes(env)

    assert (
        await service.validate(
            "add_member",
            user_id="invitee",
            name=None,
            email=None,
            role_id=str(reader.id),
        )
        == []
    )
    assert await snapshot_of_writes(env) == before


async def test_validate_raises_what_is_not_a_rule_violation(env: Env) -> None:
    with pytest.raises(NotFoundError):
        await env.service().validate("remove_member", user_id="nobody")
    await member(env, "staff")
    with pytest.raises(NotManager):
        await env.service(Actor(type="tenant_user", id="staff")).validate(
            "remove_member", user_id="staff"
        )


async def test_developer_may_remove_a_manager_while_another_remains(env: Env) -> None:
    await owner(env, "boss")
    await group_owner(env, "via-group")
    await env.service(DEVELOPER).remove_member("boss")
    assert not await env.members.is_member(TENANT, "boss")


async def test_a_project_role_held_in_the_tenant_shows_as_project(env: Env) -> None:
    project = await env.roles.create(
        make_role("Admin", permission_ids=[(await env.permission("till", "open")).id])
    )
    await member(env, "u-1", [project])

    (listed,) = [m for m in await env.service().list_members() if m.user_id == "u-1"]

    assert [(r.name, r.kind) for r in listed.roles] == [("Admin", "project")]


async def test_template_and_tenant_roles_keep_their_kind(env: Env) -> None:
    template = await env.template("Tmpl", [await env.permission("till", "open")])
    own = await tenant_role(env, "Own", [await env.permission("till", "close")])
    await member(env, "u-1", [template, own])

    (listed,) = [m for m in await env.service().list_members() if m.user_id == "u-1"]

    assert {r.name: r.kind for r in listed.roles} == {
        "Tmpl": "template",
        "Own": "tenant",
    }


async def test_role_grants_fail_closed_when_the_snapshot_lacks_the_template(
    env: Env,
) -> None:
    """A template missing from the snapshot must not yield no grants (which
    would let escalation pass vacuously): it is rendered from the repo."""
    parent = await env.template("Parent", [await env.permission("till", "close")])
    child = make_role(
        "Child",
        permission_ids=[(await env.permission("till", "open")).id],
        is_template=True,
        parent_role_id=parent.id,
    )
    child = await env.roles.create(child)
    service = env.service()

    async def empty_snapshot() -> Any:
        return make_snapshot([])

    service._snapshot_builder.build = empty_snapshot  # type: ignore[method-assign]

    grants = await service._role_grants(child)

    assert {g.permission for g in grants} == {"till:open", "till:close"}
