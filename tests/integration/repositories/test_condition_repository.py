"""Integration tests for MongoDBConditionRepository."""

from beanie import PydanticObjectId

from osiki.models.condition import Condition
from osiki.repositories.conditions.mongodb_condition_repository import (
    MongoDBConditionRepository,
)
from osiki.repositories.environment_state.mongodb_environment_state_repository import (
    MongoDBEnvironmentStateRepository,
)

EXPR = {"op": "eq", "left": {"ref": "user.id"}, "right": {"value": "u1"}}


def _cond(key: str) -> Condition:
    return Condition(key=key, name=key, expression=EXPR)


async def test_create_and_get_by_id() -> None:
    repo = MongoDBConditionRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    created = await repo.create(_cond("repo_c1"))
    assert created.id is not None
    assert await repo.get_by_id(str(created.id)) is not None
    assert await repo.get_by_id(str(PydanticObjectId())) is None


async def test_get_by_key_and_env_isolation() -> None:
    a = MongoDBConditionRepository("env-a", MongoDBEnvironmentStateRepository("env-a"))
    b = MongoDBConditionRepository("env-b", MongoDBEnvironmentStateRepository("env-b"))
    await a.create(_cond("repo_c2"))
    assert await a.get_by_key("repo_c2") is not None
    assert await b.get_by_key("repo_c2") is None
    await b.create(_cond("repo_c2"))


async def test_get_by_ids() -> None:
    repo = MongoDBConditionRepository(
        "env-ids", MongoDBEnvironmentStateRepository("env-ids")
    )
    c1 = await repo.create(_cond("ids_1"))
    c2 = await repo.create(_cond("ids_2"))
    other = await MongoDBConditionRepository(
        "env-ids-other", MongoDBEnvironmentStateRepository("env-ids-other")
    ).create(_cond("ids_3"))
    await repo.deactivate(str(c2.id))

    result = await repo.get_by_ids([str(c1.id), str(c2.id), str(other.id)])

    assert [c.key for c in result] == ["ids_1"]


async def test_update() -> None:
    repo = MongoDBConditionRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    created = await repo.create(_cond("repo_c3"))
    created.name = "changed"
    updated = await repo.update(created)
    assert updated.name == "changed"


async def test_deactivate() -> None:
    repo = MongoDBConditionRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    created = await repo.create(_cond("repo_c4"))
    assert await repo.deactivate(str(created.id)) is True
    assert await repo.deactivate(str(PydanticObjectId())) is False


async def test_list_active() -> None:
    repo = MongoDBConditionRepository(
        "env-list", MongoDBEnvironmentStateRepository("env-list")
    )
    await repo.create(_cond("list_1"))
    gone = await repo.create(_cond("list_2"))
    await repo.deactivate(str(gone.id))
    result = await repo.list_active(skip=0, limit=10)
    assert [c.key for c in result] == ["list_1"]


async def test_get_all_includes_inactive_and_stays_in_environment() -> None:
    repo = MongoDBConditionRepository(
        "env-all", MongoDBEnvironmentStateRepository("env-all")
    )
    live = await repo.create(_cond("all_live"))
    dead = await repo.create(_cond("all_dead"))
    await repo.deactivate(str(dead.id))
    await MongoDBConditionRepository(
        "env-all-other", MongoDBEnvironmentStateRepository("env-all-other")
    ).create(_cond("all_other"))

    result = await repo.get_all()

    assert {c.key for c in result} == {live.key, dead.key}
