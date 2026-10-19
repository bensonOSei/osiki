"""Environment isolation tests for the MongoDB repositories."""

from osiki.models.role import Role
from osiki.models.user import User
from osiki.repositories.environment_state.mongodb_environment_state_repository import (
    MongoDBEnvironmentStateRepository,
)
from osiki.repositories.roles.mongodb_role_repository import MongoDBRoleRepository
from osiki.repositories.users.mongodb_user_repository import MongoDBUserRepository


async def test_same_external_id_in_two_envs() -> None:
    await MongoDBUserRepository("a", MongoDBEnvironmentStateRepository("a")).create(
        User(external_id="u1")
    )
    await MongoDBUserRepository("b", MongoDBEnvironmentStateRepository("b")).create(
        User(external_id="u1")
    )

    found = await MongoDBUserRepository(
        "b", MongoDBEnvironmentStateRepository("b")
    ).get_by_external_id("u1")

    assert found is not None
    assert found.environment_id == "b"


async def test_get_by_id_does_not_cross_envs() -> None:
    role = await MongoDBRoleRepository(
        "a", MongoDBEnvironmentStateRepository("a")
    ).create(Role(name="editor"))

    assert (
        await MongoDBRoleRepository(
            "b", MongoDBEnvironmentStateRepository("b")
        ).get_by_id(str(role.id))
        is None
    )
