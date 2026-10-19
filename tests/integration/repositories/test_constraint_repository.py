"""Integration tests for MongoDBConstraintRepository."""

from beanie import PydanticObjectId

from osiki.models.constraint import Constraint, ConstraintConfig, ConstraintType
from osiki.repositories.constraints.mongodb_constraint_repository import (
    MongoDBConstraintRepository,
)
from osiki.repositories.environment_state.mongodb_environment_state_repository import (
    MongoDBEnvironmentStateRepository,
)


async def test_create() -> None:
    repo = MongoDBConstraintRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    constraint = Constraint(
        name="exclusive",
        type=ConstraintType.MUTUAL_EXCLUSION,
        config=ConstraintConfig(role_ids=[PydanticObjectId()]),
    )
    result = await repo.create(constraint)
    assert result.id is not None


async def test_get_by_id() -> None:
    repo = MongoDBConstraintRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    constraint = Constraint(
        name="cardinality",
        type=ConstraintType.CARDINALITY,
        config=ConstraintConfig(max_assignments=5),
    )
    created = await repo.create(constraint)
    result = await repo.get_by_id(str(created.id))
    assert result is not None


async def test_get_by_id_not_found() -> None:
    repo = MongoDBConstraintRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    result = await repo.get_by_id(str(PydanticObjectId()))
    assert result is None


async def test_get_active() -> None:
    repo = MongoDBConstraintRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    await repo.create(
        Constraint(
            name="c1",
            type=ConstraintType.MUTUAL_EXCLUSION,
            config=ConstraintConfig(),
        )
    )
    await repo.create(
        Constraint(
            name="c2",
            type=ConstraintType.PREREQUISITE,
            config=ConstraintConfig(),
        )
    )
    result = await repo.get_active()
    assert len(result) == 2


async def test_get_by_type() -> None:
    repo = MongoDBConstraintRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    await repo.create(
        Constraint(
            name="card-1",
            type=ConstraintType.CARDINALITY,
            config=ConstraintConfig(max_assignments=3),
        )
    )
    result = await repo.get_by_type(ConstraintType.CARDINALITY)
    assert len(result) >= 1


async def test_get_by_role_id() -> None:
    repo = MongoDBConstraintRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    role_id = PydanticObjectId()
    await repo.create(
        Constraint(
            name="role-constraint",
            type=ConstraintType.MUTUAL_EXCLUSION,
            config=ConstraintConfig(role_ids=[role_id]),
        )
    )
    result = await repo.get_by_role_id(str(role_id))
    assert len(result) >= 1


async def test_deactivate() -> None:
    repo = MongoDBConstraintRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    constraint = await repo.create(
        Constraint(
            name="to-deactivate",
            type=ConstraintType.MUTUAL_EXCLUSION,
            config=ConstraintConfig(),
        )
    )
    result = await repo.deactivate(str(constraint.id))
    assert result is True


async def test_update() -> None:
    repo = MongoDBConstraintRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    constraint = await repo.create(
        Constraint(
            name="original",
            type=ConstraintType.MUTUAL_EXCLUSION,
            config=ConstraintConfig(),
        )
    )
    constraint.name = "updated"
    result = await repo.update(constraint)
    assert result.name == "updated"

    fetched = await repo.get_by_id(str(result.id))
    assert fetched is not None
    assert fetched.name == "updated"


async def test_deactivate_not_found() -> None:
    repo = MongoDBConstraintRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    result = await repo.deactivate(str(PydanticObjectId()))
    assert result is False
