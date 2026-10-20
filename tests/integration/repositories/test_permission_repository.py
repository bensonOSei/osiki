"""Integration tests for MongoDBPermissionRepository."""

from beanie import PydanticObjectId

from osiki.models.permission import Permission
from osiki.repositories.environment_state.mongodb_environment_state_repository import (
    MongoDBEnvironmentStateRepository,
)
from osiki.repositories.permissions.mongodb_permission_repository import (
    MongoDBPermissionRepository,
)


async def test_create() -> None:
    repo = MongoDBPermissionRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    perm = Permission(resource="files", action="write")
    result = await repo.create(perm)
    assert result.id is not None
    assert result.resource == "files"
    assert result.action == "write"


async def test_get_by_id() -> None:
    repo = MongoDBPermissionRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    perm = Permission(resource="users", action="manage")
    created = await repo.create(perm)
    result = await repo.get_by_id(str(created.id))
    assert result is not None
    assert result.resource == "users"


async def test_get_by_id_not_found() -> None:
    repo = MongoDBPermissionRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    result = await repo.get_by_id(str(PydanticObjectId()))
    assert result is None


async def test_get_by_ids() -> None:
    repo = MongoDBPermissionRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    p1 = await repo.create(Permission(resource="a", action="read"))
    p2 = await repo.create(Permission(resource="b", action="read"))
    result = await repo.get_by_ids([str(p1.id), str(p2.id)])
    assert len(result) == 2


async def test_get_by_resource_action() -> None:
    repo = MongoDBPermissionRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    await repo.create(Permission(resource="settings", action="update"))
    result = await repo.get_by_resource_action("settings", "update")
    assert result is not None
    assert result.resource == "settings"


async def test_get_by_resource() -> None:
    repo = MongoDBPermissionRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    await repo.create(Permission(resource="reports", action="read"))
    await repo.create(Permission(resource="reports", action="write"))
    result = await repo.get_by_resource("reports")
    assert len(result) == 2


async def test_deactivate() -> None:
    repo = MongoDBPermissionRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    perm = await repo.create(Permission(resource="temp", action="delete"))
    result = await repo.deactivate(str(perm.id))
    assert result is True


async def test_deactivate_not_found() -> None:
    repo = MongoDBPermissionRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    result = await repo.deactivate(str(PydanticObjectId()))
    assert result is False


async def test_list_active() -> None:
    repo = MongoDBPermissionRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    await repo.create(Permission(resource="r1", action="a1"))
    await repo.create(Permission(resource="r2", action="a2"))
    result = await repo.list_active()
    assert len(result) >= 2


async def test_update_persists_assignable_and_bumps_config_version() -> None:
    state = MongoDBEnvironmentStateRepository("default")
    repo = MongoDBPermissionRepository("default", state)
    perm = await repo.create(Permission(resource="upd", action="a"))
    assert perm.assignable is False
    before = await state.get_config_version()

    perm.assignable = True
    perm.description = "changed"
    await repo.update(perm)

    loaded = await repo.get_by_id(str(perm.id))
    assert loaded is not None
    assert (loaded.assignable, loaded.description) == (True, "changed")
    assert await state.get_config_version() == before + 1


async def test_deactivate_bumps_both_versions() -> None:
    state = MongoDBEnvironmentStateRepository("default")
    repo = MongoDBPermissionRepository("default", state)
    perm = await repo.create(Permission(resource="bump", action="me"))
    config, assignments = (
        await state.get_config_version(),
        await state.get_assignments_version(),
    )

    assert await repo.deactivate(str(perm.id)) is True

    assert await state.get_config_version() == config + 1
    assert await state.get_assignments_version() == assignments + 1
