"""Integration tests for MongoDBRoleRepository."""

from beanie import PydanticObjectId

from osiki.models.permission import Permission
from osiki.models.role import Grant, Role
from osiki.repositories.permissions.mongodb_permission_repository import (
    MongoDBPermissionRepository,
)
from osiki.repositories.roles.mongodb_role_repository import MongoDBRoleRepository


async def test_create() -> None:
    repo = MongoDBRoleRepository("default")
    role = Role(name="admin-role")
    result = await repo.create(role)
    assert result.id is not None
    assert result.name == "admin-role"


async def test_get_by_id() -> None:
    repo = MongoDBRoleRepository("default")
    role = Role(name="reader-role")
    created = await repo.create(role)
    result = await repo.get_by_id(str(created.id))
    assert result is not None
    assert result.name == "reader-role"


async def test_get_by_id_not_found() -> None:
    repo = MongoDBRoleRepository("default")
    result = await repo.get_by_id(str(PydanticObjectId()))
    assert result is None


async def test_get_by_name() -> None:
    repo = MongoDBRoleRepository("default")
    role = Role(name="writer-role")
    await repo.create(role)
    result = await repo.get_by_name("writer-role")
    assert result is not None
    assert result.name == "writer-role"


async def test_get_by_ids() -> None:
    repo = MongoDBRoleRepository("default")
    r1 = await repo.create(Role(name="role-a"))
    r2 = await repo.create(Role(name="role-b"))
    result = await repo.get_by_ids([str(r1.id), str(r2.id)])
    assert len(result) == 2


async def test_get_children() -> None:
    repo = MongoDBRoleRepository("default")
    parent = await repo.create(Role(name="parent-role"))
    await repo.create(Role(name="child-1", parent_role_id=parent.id))
    await repo.create(Role(name="child-2", parent_role_id=parent.id))
    result = await repo.get_children(str(parent.id))
    assert len(result) == 2


async def test_update() -> None:
    repo = MongoDBRoleRepository("default")
    role = Role(name="update-role")
    created = await repo.create(role)
    created.description = "Updated description"
    updated = await repo.update(created)
    assert updated.description == "Updated description"


async def test_add_permission() -> None:
    repo = MongoDBRoleRepository("default")
    perm_repo = MongoDBPermissionRepository("default")
    perm = await perm_repo.create(Permission(resource="docs", action="read"))
    role = await repo.create(Role(name="role-with-perm"))
    result = await repo.add_permission(str(role.id), str(perm.id))
    assert result is True
    updated = await repo.get_by_id(str(role.id))
    assert updated is not None
    assert updated.grants == [Grant(permission_id=perm.id)]


async def test_add_permission_not_found() -> None:
    repo = MongoDBRoleRepository("default")
    result = await repo.add_permission(str(PydanticObjectId()), str(PydanticObjectId()))
    assert result is False


async def test_remove_permission() -> None:
    repo = MongoDBRoleRepository("default")
    perm_id = PydanticObjectId()
    role = await repo.create(
        Role(name="role-with-perm-2", grants=[Grant(permission_id=perm_id)])
    )
    result = await repo.remove_permission(str(role.id), str(perm_id))
    assert result is True
    updated = await repo.get_by_id(str(role.id))
    assert updated is not None
    assert updated.grants == []


async def test_remove_permission_not_found() -> None:
    repo = MongoDBRoleRepository("default")
    result = await repo.remove_permission(
        str(PydanticObjectId()), str(PydanticObjectId())
    )
    assert result is False


async def test_deactivate() -> None:
    repo = MongoDBRoleRepository("default")
    role = await repo.create(Role(name="to-deactivate-role"))
    result = await repo.deactivate(str(role.id))
    assert result is True
    updated = await repo.get_by_id(str(role.id))
    assert updated is not None
    assert updated.is_active is False


async def test_deactivate_system_role() -> None:
    repo = MongoDBRoleRepository("default")
    role = await repo.create(Role(name="system-role", is_system=True))
    result = await repo.deactivate(str(role.id))
    assert result is False


async def test_deactivate_not_found() -> None:
    repo = MongoDBRoleRepository("default")
    result = await repo.deactivate(str(PydanticObjectId()))
    assert result is False


async def test_list_active() -> None:
    repo = MongoDBRoleRepository("default")
    await repo.create(Role(name="active-role-1"))
    await repo.create(Role(name="active-role-2"))
    result = await repo.list_active()
    assert len(result) >= 2


async def test_add_permission_is_idempotent_per_exact_grant() -> None:
    repo = MongoDBRoleRepository("default")
    pid, cid = PydanticObjectId(), PydanticObjectId()
    role = await repo.create(Role(name="idem-role"))

    assert await repo.add_permission(str(role.id), str(pid)) is True
    assert await repo.add_permission(str(role.id), str(pid)) is True
    assert await repo.add_permission(str(role.id), str(pid), str(cid)) is True

    updated = await repo.get_by_id(str(role.id))
    assert updated is not None
    assert updated.grants == [
        Grant(permission_id=pid),
        Grant(permission_id=pid, condition_id=cid),
    ]


async def test_remove_exact_grant_only() -> None:
    repo = MongoDBRoleRepository("default")
    pid, cid = PydanticObjectId(), PydanticObjectId()
    role = await repo.create(
        Role(
            name="exact-role",
            grants=[
                Grant(permission_id=pid),
                Grant(permission_id=pid, condition_id=cid),
            ],
        )
    )

    assert await repo.remove_permission(str(role.id), str(pid), str(cid)) is True

    updated = await repo.get_by_id(str(role.id))
    assert updated is not None
    assert updated.grants == [Grant(permission_id=pid)]


async def test_remove_missing_grant_is_noop() -> None:
    repo = MongoDBRoleRepository("default")
    role = await repo.create(Role(name="noop-role"))

    assert await repo.remove_permission(str(role.id), str(PydanticObjectId())) is True


async def test_is_condition_in_use() -> None:
    repo = MongoDBRoleRepository("default")
    cid = PydanticObjectId()
    await repo.create(
        Role(
            name="uses-cond",
            grants=[Grant(permission_id=PydanticObjectId(), condition_id=cid)],
        )
    )
    inactive = PydanticObjectId()
    gone = await repo.create(
        Role(
            name="gone",
            grants=[Grant(permission_id=PydanticObjectId(), condition_id=inactive)],
        )
    )
    await repo.deactivate(str(gone.id))

    assert await repo.is_condition_in_use(str(cid)) is True
    assert await repo.is_condition_in_use(str(inactive)) is False
    assert await repo.is_condition_in_use(str(PydanticObjectId())) is False
    assert await MongoDBRoleRepository("other").is_condition_in_use(str(cid)) is False
