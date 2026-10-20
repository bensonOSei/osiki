"""Integration tests for MongoDBUserRoleRepository."""

import time

from beanie import PydanticObjectId

from osiki.models.base import Scope
from osiki.models.user_role import UserRole
from osiki.repositories.environment_state.mongodb_environment_state_repository import (
    MongoDBEnvironmentStateRepository,
)
from osiki.repositories.user_roles.mongodb_user_role_repository import (
    MongoDBUserRoleRepository,
)


async def test_create() -> None:
    repo = MongoDBUserRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    ur = UserRole(
        user_id=PydanticObjectId(),
        role_id=PydanticObjectId(),
        assigned_by="admin",
    )
    result = await repo.create(ur)
    assert result.id is not None


async def test_get_user_roles() -> None:
    repo = MongoDBUserRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
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
    repo = MongoDBUserRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
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
    repo = MongoDBUserRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
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
    repo = MongoDBUserRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
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
    repo = MongoDBUserRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
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
    repo = MongoDBUserRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
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
    repo = MongoDBUserRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    result = await repo.revoke(str(PydanticObjectId()))
    assert result is False


async def test_get_expired() -> None:
    repo = MongoDBUserRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
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
    repo = MongoDBUserRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
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


async def test_count_active_matches_roles_scope_and_expiry() -> None:
    repo = MongoDBUserRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    role_a, role_b, other = PydanticObjectId(), PydanticObjectId(), PydanticObjectId()
    now = time.time()
    rows = [
        (role_a, Scope(tenant_id="acme"), None),
        (role_b, Scope(tenant_id="acme", branch_id="b1"), now + 100),
        (role_a, Scope(tenant_id="acme"), now - 100),  # expired
        (role_a, Scope(tenant_id="other"), None),
        (other, Scope(tenant_id="acme"), None),
    ]
    for role_id, scope, expires_at in rows:
        await repo.create(
            UserRole(
                user_id=PydanticObjectId(),
                role_id=role_id,
                scope=scope,
                assigned_by="admin",
                expires_at=expires_at,
            )
        )
    both = [str(role_a), str(role_b)]

    assert await repo.count_active(both, {}, now) == 3
    assert await repo.count_active(both, {"tenant_id": "acme"}, now) == 2
    # Exact: the branch-scoped row no longer matches a tenant-only scope.
    assert await repo.count_active(both, {"tenant_id": "acme"}, now, exact=True) == 1
    assert await repo.count_active([str(role_b)], {"tenant_id": "acme"}, now) == 1
    assert await repo.count_active(both, {"tenant_id": "acme"}, now + 200) == 1
