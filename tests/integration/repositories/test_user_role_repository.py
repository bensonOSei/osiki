"""Integration tests for MongoDBUserRoleRepository."""

import time

from beanie import PydanticObjectId

from osiki.models.base import Scope
from osiki.models.user_role import UserRole
from osiki.repositories.user_roles.mongodb_user_role_repository import (
    MongoDBUserRoleRepository,
)


async def test_create() -> None:
    repo = MongoDBUserRoleRepository("default")
    ur = UserRole(
        user_id=PydanticObjectId(),
        role_id=PydanticObjectId(),
        assigned_by="admin",
    )
    result = await repo.create(ur)
    assert result.id is not None


async def test_get_user_roles() -> None:
    repo = MongoDBUserRoleRepository("default")
    user_id = PydanticObjectId()
    await repo.create(
        UserRole(user_id=user_id, role_id=PydanticObjectId(), assigned_by="admin")
    )
    await repo.create(
        UserRole(user_id=user_id, role_id=PydanticObjectId(), assigned_by="admin")
    )
    result = await repo.get_user_roles(str(user_id))
    assert len(result) == 2


async def test_get_users_with_role() -> None:
    repo = MongoDBUserRoleRepository("default")
    role_id = PydanticObjectId()
    await repo.create(
        UserRole(user_id=PydanticObjectId(), role_id=role_id, assigned_by="admin")
    )
    await repo.create(
        UserRole(user_id=PydanticObjectId(), role_id=role_id, assigned_by="admin")
    )
    result = await repo.get_users_with_role(str(role_id))
    assert len(result) == 2


async def test_get_by_tenant() -> None:
    repo = MongoDBUserRoleRepository("default")
    role_id = PydanticObjectId()
    await repo.create(
        UserRole(
            user_id=PydanticObjectId(),
            role_id=role_id,
            assigned_by="admin",
            scope=Scope(tenant_id="tenant-1"),
        )
    )
    await repo.create(
        UserRole(
            user_id=PydanticObjectId(),
            role_id=role_id,
            assigned_by="admin",
            scope=Scope(tenant_id="tenant-1"),
        )
    )
    result = await repo.get_by_tenant("tenant-1")
    assert len(result) == 2


async def test_get_by_tenant_with_role_filter() -> None:
    repo = MongoDBUserRoleRepository("default")
    role_id = PydanticObjectId()
    await repo.create(
        UserRole(
            user_id=PydanticObjectId(),
            role_id=role_id,
            assigned_by="admin",
            scope=Scope(tenant_id="tenant-2"),
        )
    )
    await repo.create(
        UserRole(
            user_id=PydanticObjectId(),
            role_id=PydanticObjectId(),
            assigned_by="admin",
            scope=Scope(tenant_id="tenant-2"),
        )
    )
    result = await repo.get_by_tenant("tenant-2", str(role_id))
    assert len(result) == 1


async def test_find_assignment() -> None:
    repo = MongoDBUserRoleRepository("default")
    user_id = PydanticObjectId()
    role_id = PydanticObjectId()
    await repo.create(
        UserRole(
            user_id=user_id,
            role_id=role_id,
            assigned_by="admin",
            scope=Scope(tenant_id="t1"),
        )
    )
    result = await repo.find_assignment(str(user_id), str(role_id), "t1")
    assert result is not None


async def test_revoke() -> None:
    repo = MongoDBUserRoleRepository("default")
    ur = await repo.create(
        UserRole(
            user_id=PydanticObjectId(), role_id=PydanticObjectId(), assigned_by="admin"
        )
    )
    result = await repo.revoke(str(ur.id))
    assert result is True
    updated = await repo.get_by_id(str(ur.id))
    assert updated is not None
    assert updated.is_active is False


async def test_revoke_not_found() -> None:
    repo = MongoDBUserRoleRepository("default")
    result = await repo.revoke(str(PydanticObjectId()))
    assert result is False


async def test_get_expired() -> None:
    repo = MongoDBUserRoleRepository("default")
    now = time.time()
    await repo.create(
        UserRole(
            user_id=PydanticObjectId(),
            role_id=PydanticObjectId(),
            assigned_by="admin",
            expires_at=now - 3600,
        )
    )
    result = await repo.get_expired(now)
    assert len(result) == 1


async def test_find_assignment_without_tenant_is_project_wide_only() -> None:
    repo = MongoDBUserRoleRepository("default")
    user_id, role_id = PydanticObjectId(), PydanticObjectId()
    await repo.create(
        UserRole(
            user_id=user_id,
            role_id=role_id,
            scope=Scope(tenant_id="t1"),
            assigned_by="admin",
        )
    )
    assert await repo.find_assignment(str(user_id), str(role_id)) is None

    project_wide = await repo.create(
        UserRole(user_id=user_id, role_id=role_id, assigned_by="admin")
    )
    found = await repo.find_assignment(str(user_id), str(role_id))
    assert found is not None and found.id == project_wide.id
