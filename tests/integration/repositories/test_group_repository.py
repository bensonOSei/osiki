"""Integration tests for MongoDBGroupRepository."""

from beanie import PydanticObjectId

from osiki.models.group import Group
from osiki.repositories.groups.mongodb_group_repository import MongoDBGroupRepository


async def test_create() -> None:
    repo = MongoDBGroupRepository("default")
    group = Group(name="admins")
    result = await repo.create(group)
    assert result.id is not None
    assert result.name == "admins"


async def test_get_by_id() -> None:
    repo = MongoDBGroupRepository("default")
    group = Group(name="editors")
    created = await repo.create(group)
    result = await repo.get_by_id(str(created.id))
    assert result is not None
    assert result.name == "editors"


async def test_get_by_id_not_found() -> None:
    repo = MongoDBGroupRepository("default")
    result = await repo.get_by_id(str(PydanticObjectId()))
    assert result is None


async def test_get_by_name() -> None:
    repo = MongoDBGroupRepository("default")
    group = Group(name="viewers")
    await repo.create(group)
    result = await repo.get_by_name("viewers")
    assert result is not None
    assert result.name == "viewers"


async def test_update() -> None:
    repo = MongoDBGroupRepository("default")
    group = Group(name="update-group")
    created = await repo.create(group)
    created.description = "Updated description"
    updated = await repo.update(created)
    assert updated.description == "Updated description"


async def test_deactivate() -> None:
    repo = MongoDBGroupRepository("default")
    group = Group(name="to-deactivate")
    created = await repo.create(group)
    result = await repo.deactivate(str(created.id))
    assert result is True
    updated = await repo.get_by_id(str(created.id))
    assert updated is not None
    assert updated.is_active is False


async def test_deactivate_not_found() -> None:
    repo = MongoDBGroupRepository("default")
    result = await repo.deactivate(str(PydanticObjectId()))
    assert result is False


async def test_reactivate() -> None:
    repo = MongoDBGroupRepository("default")
    group = Group(name="to-reactivate", is_active=False)
    created = await repo.create(group)
    result = await repo.reactivate(str(created.id))
    assert result is True
    updated = await repo.get_by_id(str(created.id))
    assert updated is not None
    assert updated.is_active is True


async def test_reactivate_not_found() -> None:
    repo = MongoDBGroupRepository("default")
    result = await repo.reactivate(str(PydanticObjectId()))
    assert result is False


async def test_list_active() -> None:
    repo = MongoDBGroupRepository("default")
    await repo.create(Group(name="active-group-1"))
    await repo.create(Group(name="active-group-2"))
    result = await repo.list_active()
    assert len(result) >= 2


async def test_get_by_ids_returns_only_active_groups_in_environment() -> None:
    repo = MongoDBGroupRepository("default")
    live = await repo.create(Group(name="live"))
    dead = await repo.create(Group(name="dead"))
    await repo.deactivate(str(dead.id))
    elsewhere = await MongoDBGroupRepository("other").create(Group(name="x"))

    result = await repo.get_by_ids([str(live.id), str(dead.id), str(elsewhere.id)])

    assert [g.id for g in result] == [live.id]
