"""Integration tests for MongoDBPermissionRepository."""

from beanie import PydanticObjectId

from osiki.models.permission import Permission
from osiki.repositories.permissions.mongodb_permission_repository import (
    MongoDBPermissionRepository,
)


async def test_create() -> None:
    repo = MongoDBPermissionRepository("default")
    perm = Permission(resource="files", action="write")
    result = await repo.create(perm)
    assert result.id is not None
    assert result.resource == "files"
    assert result.action == "write"


async def test_get_by_id() -> None:
    repo = MongoDBPermissionRepository("default")
    perm = Permission(resource="users", action="manage")
    created = await repo.create(perm)
    result = await repo.get_by_id(str(created.id))
    assert result is not None
    assert result.resource == "users"


async def test_get_by_id_not_found() -> None:
    repo = MongoDBPermissionRepository("default")
    result = await repo.get_by_id(str(PydanticObjectId()))
    assert result is None


async def test_get_by_ids() -> None:
    repo = MongoDBPermissionRepository("default")
    p1 = await repo.create(Permission(resource="a", action="read"))
    p2 = await repo.create(Permission(resource="b", action="read"))
    result = await repo.get_by_ids([str(p1.id), str(p2.id)])
    assert len(result) == 2


async def test_get_by_resource_action() -> None:
    repo = MongoDBPermissionRepository("default")
    await repo.create(Permission(resource="settings", action="update"))
    result = await repo.get_by_resource_action("settings", "update")
    assert result is not None
    assert result.resource == "settings"


async def test_get_by_resource() -> None:
    repo = MongoDBPermissionRepository("default")
    await repo.create(Permission(resource="reports", action="read"))
    await repo.create(Permission(resource="reports", action="write"))
    result = await repo.get_by_resource("reports")
    assert len(result) == 2


async def test_deactivate() -> None:
    repo = MongoDBPermissionRepository("default")
    perm = await repo.create(Permission(resource="temp", action="delete"))
    result = await repo.deactivate(str(perm.id))
    assert result is True


async def test_deactivate_not_found() -> None:
    repo = MongoDBPermissionRepository("default")
    result = await repo.deactivate(str(PydanticObjectId()))
    assert result is False


async def test_list_active() -> None:
    repo = MongoDBPermissionRepository("default")
    await repo.create(Permission(resource="r1", action="a1"))
    await repo.create(Permission(resource="r2", action="a2"))
    result = await repo.list_active()
    assert len(result) >= 2
