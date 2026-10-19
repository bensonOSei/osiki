"""Assign -> revoke -> assign -> revoke must succeed and leave nothing active.

The unique indexes on assignments only cover active rows (a partial index on
``is_active: true``), so any number of revoked rows can pile up for the same
key. Each test ends by building the user's bundle with the MongoDB repositories
and deciding against a snapshot whose role grants ``docs:read``: it must deny.
"""

import pytest
from beanie import PydanticObjectId
from pymongo.errors import DuplicateKeyError

from osiki.decision.decide import decide
from osiki.decision.models import (
    DecisionRequest,
    GrantEntry,
    RoleEntry,
    Snapshot,
    UserBundle,
)
from osiki.models.base import Scope
from osiki.models.group import Group
from osiki.models.group_role import GroupRole
from osiki.models.user import User
from osiki.models.user_group import UserGroup
from osiki.models.user_role import UserRole
from osiki.repositories.environment_state.mongodb_environment_state_repository import (
    MongoDBEnvironmentStateRepository,
)
from osiki.repositories.group_roles.mongodb_group_role_repository import (
    MongoDBGroupRoleRepository,
)
from osiki.repositories.groups.mongodb_group_repository import MongoDBGroupRepository
from osiki.repositories.tenant_members.mongodb_tenant_member_repository import (
    MongoDBTenantMemberRepository,
)
from osiki.repositories.tenants.mongodb_tenant_repository import (
    MongoDBTenantRepository,
)
from osiki.repositories.user_groups.mongodb_user_group_repository import (
    MongoDBUserGroupRepository,
)
from osiki.repositories.user_roles.mongodb_user_role_repository import (
    MongoDBUserRoleRepository,
)
from osiki.repositories.users.mongodb_user_repository import MongoDBUserRepository
from osiki.services.bundle_builder.bundle_builder import BundleBuilder

ENV = "default"


async def _bundle(external_id: str) -> UserBundle:
    builder = BundleBuilder(
        MongoDBUserRepository(ENV, MongoDBEnvironmentStateRepository(ENV)),
        MongoDBUserRoleRepository(ENV, MongoDBEnvironmentStateRepository(ENV)),
        MongoDBUserGroupRepository(ENV, MongoDBEnvironmentStateRepository(ENV)),
        MongoDBGroupRepository(ENV, MongoDBEnvironmentStateRepository(ENV)),
        MongoDBGroupRoleRepository(ENV, MongoDBEnvironmentStateRepository(ENV)),
        MongoDBTenantMemberRepository(ENV, MongoDBEnvironmentStateRepository(ENV)),
        MongoDBTenantRepository(ENV, MongoDBEnvironmentStateRepository(ENV)),
    )
    bundle = await builder.build(external_id)
    assert bundle is not None
    return bundle


def _allowed(bundle: UserBundle, role_id: PydanticObjectId) -> bool:
    snapshot = Snapshot(
        environment_id=ENV,
        version=1,
        roles=[
            RoleEntry(
                id=str(role_id),
                name="reader",
                grants=[GrantEntry(permission="docs:read")],
            )
        ],
    )
    request = DecisionRequest(resource="docs", action="read", scope={}, now=1000)
    return decide(snapshot, bundle, request).allowed


async def test_user_role_assign_revoke_twice() -> None:
    user = await MongoDBUserRepository(
        ENV, MongoDBEnvironmentStateRepository(ENV)
    ).create(User(external_id="u1"))
    assert user.id is not None
    repo = MongoDBUserRoleRepository(ENV, MongoDBEnvironmentStateRepository(ENV))
    role_id = PydanticObjectId()

    for _ in range(2):
        assignment = await repo.create(
            UserRole(user_id=user.id, role_id=role_id, assigned_by="admin")
        )
        assert _allowed(await _bundle("u1"), role_id)
        assert await repo.revoke(str(assignment.id)) is True

    assert await repo.find_assignment(str(user.id), str(role_id)) is None
    assert await repo.get_user_roles(str(user.id)) == []
    assert await UserRole.find(UserRole.user_id == user.id).count() == 2
    assert not _allowed(await _bundle("u1"), role_id)


async def test_tenant_scoped_user_role_assign_revoke_twice() -> None:
    repo = MongoDBUserRoleRepository(ENV, MongoDBEnvironmentStateRepository(ENV))
    user_id, role_id = PydanticObjectId(), PydanticObjectId()

    for _ in range(2):
        assignment = await repo.create(
            UserRole(
                user_id=user_id,
                role_id=role_id,
                scope=Scope(tenant_id="t"),
                assigned_by="admin",
            )
        )
        assert await repo.revoke(str(assignment.id)) is True

    assert await repo.find_assignment(str(user_id), str(role_id), "t") is None


async def test_group_role_assign_revoke_twice() -> None:
    user = await MongoDBUserRepository(
        ENV, MongoDBEnvironmentStateRepository(ENV)
    ).create(User(external_id="u1"))
    group = await MongoDBGroupRepository(
        ENV, MongoDBEnvironmentStateRepository(ENV)
    ).create(Group(name="g"))
    assert user.id is not None and group.id is not None
    await MongoDBUserGroupRepository(
        ENV, MongoDBEnvironmentStateRepository(ENV)
    ).create(UserGroup(user_id=user.id, group_id=group.id, added_by="admin"))
    repo = MongoDBGroupRoleRepository(ENV, MongoDBEnvironmentStateRepository(ENV))
    role_id = PydanticObjectId()

    for _ in range(2):
        assignment = await repo.create(
            GroupRole(group_id=group.id, role_id=role_id, assigned_by="admin")
        )
        assert _allowed(await _bundle("u1"), role_id)
        assert await repo.revoke(str(assignment.id)) is True

    assert await repo.find_assignment(str(group.id), str(role_id)) is None
    assert await repo.get_group_roles(str(group.id)) == []
    assert not _allowed(await _bundle("u1"), role_id)


async def test_group_membership_add_remove_twice() -> None:
    user = await MongoDBUserRepository(
        ENV, MongoDBEnvironmentStateRepository(ENV)
    ).create(User(external_id="u1"))
    group = await MongoDBGroupRepository(
        ENV, MongoDBEnvironmentStateRepository(ENV)
    ).create(Group(name="g"))
    assert user.id is not None and group.id is not None
    role_id = PydanticObjectId()
    await MongoDBGroupRoleRepository(
        ENV, MongoDBEnvironmentStateRepository(ENV)
    ).create(GroupRole(group_id=group.id, role_id=role_id, assigned_by="admin"))
    repo = MongoDBUserGroupRepository(ENV, MongoDBEnvironmentStateRepository(ENV))

    for _ in range(2):
        membership = await repo.create(
            UserGroup(user_id=user.id, group_id=group.id, added_by="admin")
        )
        assert _allowed(await _bundle("u1"), role_id)
        assert await repo.remove(str(membership.id)) is True

    assert await repo.find_membership(str(user.id), str(group.id)) is None
    assert await repo.get_group_members(str(group.id)) == []
    assert not _allowed(await _bundle("u1"), role_id)


async def test_second_active_assignment_is_still_rejected() -> None:
    """The partial index still forbids two active rows for the same key."""
    repo = MongoDBUserRoleRepository(ENV, MongoDBEnvironmentStateRepository(ENV))
    user_id, role_id = PydanticObjectId(), PydanticObjectId()
    await repo.create(UserRole(user_id=user_id, role_id=role_id, assigned_by="a"))

    with pytest.raises(DuplicateKeyError):
        await repo.create(UserRole(user_id=user_id, role_id=role_id, assigned_by="a"))
