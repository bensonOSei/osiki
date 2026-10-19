"""Integration tests for the config version and the writes that bump it."""

from collections.abc import Awaitable, Callable

import pytest
from beanie import PydanticObjectId

from osiki.models.condition import Condition
from osiki.models.constraint import Constraint, ConstraintConfig, ConstraintType
from osiki.models.permission import Permission
from osiki.models.role import Role
from osiki.repositories.conditions.mongodb_condition_repository import (
    MongoDBConditionRepository,
)
from osiki.repositories.constraints.mongodb_constraint_repository import (
    MongoDBConstraintRepository,
)
from osiki.repositories.endpoints.mongodb_endpoint_repository import (
    MongoDBEndpointRepository,
)
from osiki.repositories.environment_state.mongodb_environment_state_repository import (
    MongoDBEnvironmentStateRepository,
)
from osiki.repositories.permissions.mongodb_permission_repository import (
    MongoDBPermissionRepository,
)
from osiki.repositories.roles.mongodb_role_repository import MongoDBRoleRepository
from osiki.services.snapshot_builder import SnapshotBuilder, SnapshotCache
from tests.mocks import make_environment_state

ENV = "default"
EXPR = {"op": "eq", "left": {"ref": "record.team_id"}, "right": {"ref": "user.team_id"}}


async def test_config_version_is_zero_when_absent() -> None:
    assert await MongoDBEnvironmentStateRepository(ENV).get_config_version() == 0


async def test_bump_increments_and_returns_the_new_version() -> None:
    state = MongoDBEnvironmentStateRepository(ENV)

    assert await state.bump_config_version() == 1
    assert await state.bump_config_version() == 2
    assert await state.get_config_version() == 2


async def test_bump_is_scoped_to_its_environment() -> None:
    await MongoDBEnvironmentStateRepository("a").bump_config_version()

    assert await MongoDBEnvironmentStateRepository("b").get_config_version() == 0


type Write = Callable[[MongoDBEnvironmentStateRepository], Awaitable[object]]


def _roles(state: MongoDBEnvironmentStateRepository) -> MongoDBRoleRepository:
    return MongoDBRoleRepository(ENV, state)


def _perms(state: MongoDBEnvironmentStateRepository) -> MongoDBPermissionRepository:
    return MongoDBPermissionRepository(ENV, state)


def _conds(state: MongoDBEnvironmentStateRepository) -> MongoDBConditionRepository:
    return MongoDBConditionRepository(ENV, state)


def _cons(state: MongoDBEnvironmentStateRepository) -> MongoDBConstraintRepository:
    return MongoDBConstraintRepository(ENV, state)


async def _role(state: MongoDBEnvironmentStateRepository) -> Role:
    return await _roles(state).create(Role(name="r"))


async def _perm(state: MongoDBEnvironmentStateRepository) -> Permission:
    return await _perms(state).create(Permission(resource="docs", action="read"))


async def _cond(state: MongoDBEnvironmentStateRepository) -> Condition:
    return await _conds(state).create(
        Condition(key="own_team", name="Own team", expression=EXPR)
    )


async def _constraint(state: MongoDBEnvironmentStateRepository) -> Constraint:
    return await _cons(state).create(
        Constraint(
            name="c",
            type=ConstraintType.CARDINALITY,
            config=ConstraintConfig(role_id=PydanticObjectId(), max_assignments=1),
        )
    )


async def _role_update(state: MongoDBEnvironmentStateRepository) -> Write:
    role = await _role(state)
    role.description = "changed"
    return lambda s: _roles(s).update(role)


async def _role_deactivate(state: MongoDBEnvironmentStateRepository) -> Write:
    role = await _role(state)
    return lambda s: _roles(s).deactivate(str(role.id))


async def _role_add_permission(state: MongoDBEnvironmentStateRepository) -> Write:
    role = await _role(state)
    perm = await _perm(state)
    return lambda s: _roles(s).add_permission(str(role.id), str(perm.id))


async def _role_remove_permission(state: MongoDBEnvironmentStateRepository) -> Write:
    role = await _role(state)
    perm = await _perm(state)
    await _roles(state).add_permission(str(role.id), str(perm.id))
    return lambda s: _roles(s).remove_permission(str(role.id), str(perm.id))


async def _role_create(state: MongoDBEnvironmentStateRepository) -> Write:
    return _role


async def _perm_create(state: MongoDBEnvironmentStateRepository) -> Write:
    return _perm


async def _perm_deactivate(state: MongoDBEnvironmentStateRepository) -> Write:
    perm = await _perm(state)
    return lambda s: _perms(s).deactivate(str(perm.id))


async def _cond_create(state: MongoDBEnvironmentStateRepository) -> Write:
    return _cond


async def _cond_update(state: MongoDBEnvironmentStateRepository) -> Write:
    cond = await _cond(state)
    cond.name = "changed"
    return lambda s: _conds(s).update(cond)


async def _cond_deactivate(state: MongoDBEnvironmentStateRepository) -> Write:
    cond = await _cond(state)
    return lambda s: _conds(s).deactivate(str(cond.id))


async def _constraint_create(state: MongoDBEnvironmentStateRepository) -> Write:
    return _constraint


async def _constraint_update(state: MongoDBEnvironmentStateRepository) -> Write:
    constraint = await _constraint(state)
    constraint.description = "changed"
    return lambda s: _cons(s).update(constraint)


async def _constraint_deactivate(state: MongoDBEnvironmentStateRepository) -> Write:
    constraint = await _constraint(state)
    return lambda s: _cons(s).deactivate(str(constraint.id))


Setup = Callable[[MongoDBEnvironmentStateRepository], Awaitable[Write]]


@pytest.mark.parametrize(
    "setup",
    [
        _role_create,
        _role_update,
        _role_deactivate,
        _role_add_permission,
        _role_remove_permission,
        _perm_create,
        _perm_deactivate,
        _cond_create,
        _cond_update,
        _cond_deactivate,
        _constraint_create,
        _constraint_update,
        _constraint_deactivate,
    ],
    ids=lambda f: f.__name__.lstrip("_"),
)
async def test_version_bumps_on_every_config_write(setup: Setup) -> None:
    state = MongoDBEnvironmentStateRepository(ENV)
    write = await setup(state)
    before = await state.get_config_version()

    await write(state)

    assert await state.get_config_version() > before


async def test_failed_writes_do_not_bump() -> None:
    state = MongoDBEnvironmentStateRepository(ENV)
    missing = str(PydanticObjectId())
    system = await _roles(state).create(Role(name="sys", is_system=True))
    before = await state.get_config_version()

    assert await _roles(state).deactivate(missing) is False
    assert await _roles(state).deactivate(str(system.id)) is False
    assert await _roles(state).add_permission(missing, missing) is False
    assert await _roles(state).remove_permission(missing, missing) is False
    assert await _perms(state).deactivate(missing) is False
    assert await _conds(state).deactivate(missing) is False
    assert await _cons(state).deactivate(missing) is False

    assert await state.get_config_version() == before


async def test_reads_a_stored_state_document() -> None:
    await make_environment_state("stored", config_version=5).insert()

    assert await MongoDBEnvironmentStateRepository("stored").get_config_version() == 5
    assert await MongoDBEnvironmentStateRepository("stored").bump_config_version() == 6


async def test_snapshot_over_mongo_rebuilds_after_a_write() -> None:
    state = MongoDBEnvironmentStateRepository(ENV)
    builder = SnapshotBuilder(
        ENV,
        state,
        _roles(state),
        _perms(state),
        _conds(state),
        _cons(state),
        MongoDBEndpointRepository(ENV, state),
        cache=SnapshotCache(),
    )
    perm = await _perm(state)
    role = await _roles(state).create(Role(name="reader"))
    await _roles(state).add_permission(str(role.id), str(perm.id))

    first = await builder.build()
    assert first.roles[0].grants[0].permission == "docs:read"
    assert await builder.build() is first

    await _perms(state).deactivate(str(perm.id))

    second = await builder.build()
    assert second.version > first.version
    assert second.roles[0].grants == []
