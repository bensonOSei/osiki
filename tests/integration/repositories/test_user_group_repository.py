"""Integration tests for MongoDBUserGroupRepository."""

from beanie import PydanticObjectId

from osiki.models.user_group import UserGroup
from osiki.repositories.user_groups.mongodb_user_group_repository import (
    MongoDBUserGroupRepository,
)


async def test_create() -> None:
    repo = MongoDBUserGroupRepository()
    ug = UserGroup(
        user_id=PydanticObjectId(), group_id=PydanticObjectId(), added_by="admin"
    )
    result = await repo.create(ug)
    assert result.id is not None


async def test_get_user_groups() -> None:
    repo = MongoDBUserGroupRepository()
    user_id = PydanticObjectId()
    await repo.create(
        UserGroup(user_id=user_id, group_id=PydanticObjectId(), added_by="admin")
    )
    await repo.create(
        UserGroup(user_id=user_id, group_id=PydanticObjectId(), added_by="admin")
    )
    result = await repo.get_user_groups(str(user_id))
    assert len(result) == 2


async def test_get_group_members() -> None:
    repo = MongoDBUserGroupRepository()
    group_id = PydanticObjectId()
    await repo.create(
        UserGroup(user_id=PydanticObjectId(), group_id=group_id, added_by="admin")
    )
    await repo.create(
        UserGroup(user_id=PydanticObjectId(), group_id=group_id, added_by="admin")
    )
    result = await repo.get_group_members(str(group_id))
    assert len(result) == 2


async def test_find_membership() -> None:
    repo = MongoDBUserGroupRepository()
    user_id = PydanticObjectId()
    group_id = PydanticObjectId()
    await repo.create(UserGroup(user_id=user_id, group_id=group_id, added_by="admin"))
    result = await repo.find_membership(str(user_id), str(group_id))
    assert result is not None


async def test_remove() -> None:
    repo = MongoDBUserGroupRepository()
    ug = await repo.create(
        UserGroup(
            user_id=PydanticObjectId(), group_id=PydanticObjectId(), added_by="admin"
        )
    )
    result = await repo.remove(str(ug.id))
    assert result is True


async def test_remove_not_found() -> None:
    repo = MongoDBUserGroupRepository()
    result = await repo.remove(str(PydanticObjectId()))
    assert result is False
