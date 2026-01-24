"""Integration tests for MongoDBUserRepository."""

from beanie import PydanticObjectId

from osiki.models.user import User
from osiki.repositories.users.mongodb_user_repository import MongoDBUserRepository


async def test_create() -> None:
    repo = MongoDBUserRepository()
    user = User(external_id="ext-1", email="test@test.com")
    result = await repo.create(user)
    assert result.id is not None
    assert result.external_id == "ext-1"


async def test_get_by_id() -> None:
    repo = MongoDBUserRepository()
    user = User(external_id="ext-2")
    created = await repo.create(user)
    result = await repo.get_by_id(str(created.id))
    assert result is not None
    assert result.external_id == "ext-2"


async def test_get_by_id_not_found() -> None:
    repo = MongoDBUserRepository()
    result = await repo.get_by_id(str(PydanticObjectId()))
    assert result is None


async def test_get_by_external_id() -> None:
    repo = MongoDBUserRepository()
    user = User(external_id="ext-3")
    await repo.create(user)
    result = await repo.get_by_external_id("ext-3")
    assert result is not None
    assert result.external_id == "ext-3"


async def test_get_by_external_id_not_found() -> None:
    repo = MongoDBUserRepository()
    result = await repo.get_by_external_id("nonexistent")
    assert result is None


async def test_get_by_email() -> None:
    repo = MongoDBUserRepository()
    user = User(external_id="email-test", email="email@test.com")
    await repo.create(user)
    result = await repo.get_by_email("email@test.com")
    assert result is not None
    assert result.email == "email@test.com"


async def test_update() -> None:
    repo = MongoDBUserRepository()
    user = User(external_id="update-test")
    created = await repo.create(user)
    created.email = "updated@test.com"
    updated = await repo.update(created)
    assert updated.email == "updated@test.com"


async def test_deactivate() -> None:
    repo = MongoDBUserRepository()
    user = User(external_id="ext-4")
    created = await repo.create(user)
    result = await repo.deactivate(str(created.id))
    assert result is True
    updated = await repo.get_by_id(str(created.id))
    assert updated is not None
    assert updated.is_active is False


async def test_deactivate_not_found() -> None:
    repo = MongoDBUserRepository()
    result = await repo.deactivate(str(PydanticObjectId()))
    assert result is False


async def test_reactivate() -> None:
    repo = MongoDBUserRepository()
    user = User(external_id="ext-5", is_active=False)
    created = await repo.create(user)
    result = await repo.reactivate(str(created.id))
    assert result is True
    updated = await repo.get_by_id(str(created.id))
    assert updated is not None
    assert updated.is_active is True


async def test_reactivate_not_found() -> None:
    repo = MongoDBUserRepository()
    result = await repo.reactivate(str(PydanticObjectId()))
    assert result is False


async def test_list_active() -> None:
    repo = MongoDBUserRepository()
    await repo.create(User(external_id="active-1"))
    await repo.create(User(external_id="active-2"))
    user3 = await repo.create(User(external_id="inactive"))
    await repo.deactivate(str(user3.id))

    result = await repo.list_active()
    assert len(result) == 2
