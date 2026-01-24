"""Integration tests for MongoDBGroupRoleRepository."""

import time

from beanie import PydanticObjectId

from osiki.models.base import Scope
from osiki.models.group_role import GroupRole
from osiki.repositories.group_roles.mongodb_group_role_repository import (
    MongoDBGroupRoleRepository,
)


async def test_create() -> None:
    repo = MongoDBGroupRoleRepository()
    gr = GroupRole(
        group_id=PydanticObjectId(), role_id=PydanticObjectId(), assigned_by="admin"
    )
    result = await repo.create(gr)
    assert result.id is not None


async def test_get_group_roles() -> None:
    repo = MongoDBGroupRoleRepository()
    group_id = PydanticObjectId()
    await repo.create(
        GroupRole(group_id=group_id, role_id=PydanticObjectId(), assigned_by="admin")
    )
    await repo.create(
        GroupRole(group_id=group_id, role_id=PydanticObjectId(), assigned_by="admin")
    )
    result = await repo.get_group_roles(str(group_id))
    assert len(result) == 2


async def test_get_roles_for_groups() -> None:
    repo = MongoDBGroupRoleRepository()
    group1 = PydanticObjectId()
    group2 = PydanticObjectId()
    await repo.create(
        GroupRole(group_id=group1, role_id=PydanticObjectId(), assigned_by="admin")
    )
    await repo.create(
        GroupRole(group_id=group2, role_id=PydanticObjectId(), assigned_by="admin")
    )
    result = await repo.get_roles_for_groups([str(group1), str(group2)])
    assert len(result) == 2


async def test_get_groups_with_role() -> None:
    repo = MongoDBGroupRoleRepository()
    role_id = PydanticObjectId()
    await repo.create(
        GroupRole(group_id=PydanticObjectId(), role_id=role_id, assigned_by="admin")
    )
    await repo.create(
        GroupRole(group_id=PydanticObjectId(), role_id=role_id, assigned_by="admin")
    )
    result = await repo.get_groups_with_role(str(role_id))
    assert len(result) == 2


async def test_find_assignment() -> None:
    repo = MongoDBGroupRoleRepository()
    group_id = PydanticObjectId()
    role_id = PydanticObjectId()
    await repo.create(
        GroupRole(
            group_id=group_id,
            role_id=role_id,
            assigned_by="admin",
            scope=Scope(tenant_id="t1"),
        )
    )
    result = await repo.find_assignment(str(group_id), str(role_id), "t1")
    assert result is not None


async def test_revoke() -> None:
    repo = MongoDBGroupRoleRepository()
    gr = await repo.create(
        GroupRole(
            group_id=PydanticObjectId(), role_id=PydanticObjectId(), assigned_by="admin"
        )
    )
    result = await repo.revoke(str(gr.id))
    assert result is True


async def test_revoke_not_found() -> None:
    repo = MongoDBGroupRoleRepository()
    result = await repo.revoke(str(PydanticObjectId()))
    assert result is False


async def test_get_expired() -> None:
    repo = MongoDBGroupRoleRepository()
    now = time.time()
    await repo.create(
        GroupRole(
            group_id=PydanticObjectId(),
            role_id=PydanticObjectId(),
            assigned_by="admin",
            expires_at=now - 3600,
        )
    )
    result = await repo.get_expired(now)
    assert len(result) == 1
