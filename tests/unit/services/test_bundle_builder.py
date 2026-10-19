"""Unit tests for BundleBuilder."""

import pytest
from beanie import PydanticObjectId

from osiki.decision.models import AssignmentEntry, GrantEntry, RoleEntry
from osiki.models.base import Scope
from osiki.models.role import Grant
from osiki.models.user import User
from osiki.services.bundle_builder import BundleBuilder
from tests.mocks import (
    MockConditionRepository,
    MockEnvironmentStateRepository,
    MockGroupRepository,
    MockGroupRoleRepository,
    MockPermissionRepository,
    MockRoleRepository,
    MockTenantMemberRepository,
    MockTenantRepository,
    MockUserGroupRepository,
    MockUserRepository,
    MockUserRoleRepository,
    make_condition,
    make_group,
    make_group_role,
    make_permission,
    make_role,
    make_user,
    make_user_group,
    make_user_role,
)


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

    def builder(self) -> BundleBuilder:
        return BundleBuilder(
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


@pytest.fixture
def env() -> Env:
    return Env()


@pytest.fixture
async def user(env: Env) -> User:
    user = make_user(external_id="ext-1")
    user.attributes = {"team_id": "t1"}
    return await env.users.create(user)


async def test_unknown_user_has_no_bundle(env: Env) -> None:
    assert await env.builder().build("nobody") is None


async def test_inactive_user_has_no_bundle(env: Env, user: User) -> None:
    await env.users.deactivate(str(user.id))

    assert await env.builder().build("ext-1") is None


async def test_bundle_uses_external_id_and_attributes(env: Env, user: User) -> None:
    bundle = await env.builder().build("ext-1")

    assert bundle is not None
    assert bundle.user_id == "ext-1"
    assert bundle.attributes == {"team_id": "t1"}
    assert bundle.tenants == {}
    assert bundle.assignments == []


async def test_bundle_flattens_group_assignments_with_via_group(
    env: Env, user: User
) -> None:
    direct_role = PydanticObjectId()
    group_role = PydanticObjectId()
    group = (await env.groups.create(make_group())).id
    await env.user_roles.create(
        make_user_role(
            user_id=user.id,
            role_id=direct_role,
            scope=Scope(tenant_id="acme"),
            expires_at=2000.0,
        )
    )
    await env.user_groups.create(make_user_group(user_id=user.id, group_id=group))
    await env.group_roles.create(make_group_role(group_id=group, role_id=group_role))
    # Another group's role never reaches this user.
    await env.group_roles.create(
        make_group_role(group_id=PydanticObjectId(), role_id=PydanticObjectId())
    )

    bundle = await env.builder().build("ext-1")

    assert bundle is not None
    assert bundle.assignments == [
        AssignmentEntry(
            role_id=str(direct_role),
            scope={"tenant_id": "acme"},
            expires_at=2000.0,
            via="direct",
        ),
        AssignmentEntry(role_id=str(group_role), scope={}, via="group"),
    ]


async def test_bundle_skips_revoked_assignments(env: Env, user: User) -> None:
    group = (await env.groups.create(make_group())).id
    ur = await env.user_roles.create(
        make_user_role(user_id=user.id, role_id=PydanticObjectId())
    )
    await env.user_roles.revoke(str(ur.id))
    ug = await env.user_groups.create(make_user_group(user_id=user.id, group_id=group))
    await env.group_roles.create(
        make_group_role(group_id=group, role_id=PydanticObjectId())
    )
    await env.user_groups.remove(str(ug.id))

    bundle = await env.builder().build("ext-1")

    assert bundle is not None
    assert bundle.assignments == []


async def test_bundle_includes_tenant_attributes(env: Env, user: User) -> None:
    await env.tenants.upsert("acme", "Acme", {"region": "eu"})
    await env.tenants.upsert("beta", "Beta", {})
    await env.members.add("acme", "ext-1")
    await env.members.add("beta", "ext-1")
    await env.members.add("acme", "someone-else")

    bundle = await env.builder().build("ext-1")

    assert bundle is not None
    assert bundle.tenants == {"acme": {"region": "eu"}, "beta": {}}


async def test_membership_without_active_tenant_is_omitted(
    env: Env, user: User
) -> None:
    gone = await env.tenants.upsert("gone", "Gone", {})
    gone.is_active = False
    await env.members.add("gone", "ext-1")
    await env.members.add("never-created", "ext-1")

    bundle = await env.builder().build("ext-1")

    assert bundle is not None
    assert bundle.tenants == {}


async def test_deactivated_or_missing_group_grants_nothing(
    env: Env, user: User
) -> None:
    dead = await env.groups.create(make_group(name="dead"))
    await env.groups.deactivate(str(dead.id))
    missing = PydanticObjectId()
    for group_id in (dead.id, missing):
        await env.user_groups.create(
            make_user_group(user_id=user.id, group_id=group_id)
        )
        await env.group_roles.create(
            make_group_role(group_id=group_id, role_id=PydanticObjectId())
        )

    bundle = await env.builder().build("ext-1")

    assert bundle is not None
    assert bundle.assignments == []


async def test_bundle_carries_only_referenced_active_tenant_roles(
    env: Env, user: User
) -> None:
    read = await env.permissions.create(make_permission("sales", "create"))
    dead = make_permission("sales", "void")
    dead.is_active = False
    dead = await env.permissions.create(dead)
    cond = await env.conditions.create(make_condition("own"))
    direct = await env.roles.create(
        make_role(
            "Weekend cashier",
            grants=[
                Grant(permission_id=read.id, condition_id=cond.id),
                Grant(permission_id=dead.id),
            ],
            tenant_id="t1",
        )
    )
    grouped = await env.roles.create(
        make_role("Grouped", permission_ids=[read.id], tenant_id="t1")
    )
    project = await env.roles.create(make_role("Project", permission_ids=[read.id]))
    await env.roles.create(make_role("Unused", tenant_id="t1"))
    inactive = await env.roles.create(
        make_role("Gone", tenant_id="t1", is_active=False)
    )
    group = (await env.groups.create(make_group())).id
    await env.user_groups.create(make_user_group(user_id=user.id, group_id=group))
    await env.group_roles.create(make_group_role(group_id=group, role_id=grouped.id))
    for role in (direct, project, inactive):
        await env.user_roles.create(make_user_role(user_id=user.id, role_id=role.id))

    bundle = await env.builder().build("ext-1")

    assert bundle is not None
    assert bundle.roles == [
        RoleEntry(
            id=str(direct.id),
            name="Weekend cashier",
            grants=[GrantEntry(permission="sales:create", condition="own")],
        ),
        RoleEntry(
            id=str(grouped.id),
            name="Grouped",
            grants=[GrantEntry(permission="sales:create")],
        ),
    ]
