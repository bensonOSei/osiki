import pytest
from pymongo.errors import DuplicateKeyError

from osiki.models.permission import Permission
from osiki.models.role import Role
from osiki.services.builtins import (
    BUILTIN_TEAM_MANAGE,
    OWNER_TEMPLATE_NAME,
    BuiltinConflictError,
    ensure_builtins,
    is_builtin,
)
from tests.mocks import (
    MockEnvironmentStateRepository,
    MockPermissionRepository,
    MockRoleRepository,
    make_permission,
    make_role,
)


class Env:
    def __init__(self) -> None:
        state = MockEnvironmentStateRepository("default")
        self.state = state
        self.permissions = MockPermissionRepository("default", state)
        self.roles = MockRoleRepository("default", state)


@pytest.fixture
def env() -> Env:
    return Env()


@pytest.mark.parametrize(
    ("resource", "expected"),
    [
        ("osiki.team", True),
        ("osiki.x.y", True),
        ("osiki", False),
        ("osikix.team", False),
        ("Osiki.team", False),
        ("docs", False),
    ],
)
def test_is_builtin(resource: str, expected: bool) -> None:
    assert is_builtin(make_permission(resource, "read")) is expected


async def test_creates_permission_and_owner_template(env: Env) -> None:
    result = await ensure_builtins(env.permissions, env.roles)

    permission = await env.permissions.get_by_id(result.team_manage_permission_id)
    owner = await env.roles.get_by_id(result.owner_role_id)
    assert permission is not None
    assert (permission.resource, permission.action) == BUILTIN_TEAM_MANAGE
    assert permission.assignable is False
    assert owner is not None
    assert (owner.name, owner.tenant_id) == (OWNER_TEMPLATE_NAME, None)
    assert (owner.is_template, owner.is_system) == (True, True)
    assert [str(g.permission_id) for g in owner.grants] == [
        result.team_manage_permission_id
    ]
    assert [g.condition_id for g in owner.grants] == [None]


async def test_is_idempotent_and_never_duplicates(env: Env) -> None:
    first = await ensure_builtins(env.permissions, env.roles)
    version = await env.state.get_config_version()
    second = await ensure_builtins(env.permissions, env.roles)

    assert first == second
    assert await env.state.get_config_version() == version
    assert len(await env.permissions.get_by_resource("osiki.team")) == 1
    assert len(await env.roles.list_templates()) == 1


async def test_reuses_an_existing_permission(env: Env) -> None:
    existing = await env.permissions.create(make_permission(*BUILTIN_TEAM_MANAGE))

    result = await ensure_builtins(env.permissions, env.roles)

    assert result.team_manage_permission_id == str(existing.id)


async def test_a_plain_role_named_owner_is_a_conflict(env: Env) -> None:
    await env.roles.create(make_role(name=OWNER_TEMPLATE_NAME))

    with pytest.raises(BuiltinConflictError):
        await ensure_builtins(env.permissions, env.roles)
    assert len(await env.roles.get_all_active()) == 1


async def test_a_tenant_role_named_owner_is_not_a_conflict(env: Env) -> None:
    await env.roles.create(make_role(name=OWNER_TEMPLATE_NAME, tenant_id="acme"))

    result = await ensure_builtins(env.permissions, env.roles)

    owner = await env.roles.get_by_id(result.owner_role_id)
    assert owner is not None
    assert owner.tenant_id is None


class _RacingPermissions(MockPermissionRepository):
    """Another bootstrap creates the permission between our read and write."""

    async def create(self, permission: Permission) -> Permission:
        await super().create(make_permission(permission.resource, permission.action))
        raise DuplicateKeyError("E11000 duplicate key")


class _RacingRoles(MockRoleRepository):
    """Another bootstrap creates the template between our read and write."""

    async def create(self, role: Role) -> Role:  # type: ignore[override]
        await super().create(
            make_role(name=role.name, is_template=True, is_system=True)
        )
        raise DuplicateKeyError("E11000 duplicate key")


async def test_losing_the_permission_race_uses_the_winner(env: Env) -> None:
    permissions = _RacingPermissions("default", env.state)

    result = await ensure_builtins(permissions, env.roles)

    winner = await permissions.get_by_resource_action(*BUILTIN_TEAM_MANAGE)
    assert winner is not None
    assert result.team_manage_permission_id == str(winner.id)
    assert len(await permissions.get_by_resource("osiki.team")) == 1


async def test_losing_the_role_race_uses_the_winner(env: Env) -> None:
    roles = _RacingRoles("default", env.state)

    result = await ensure_builtins(env.permissions, roles)

    winner = await roles.get_by_name(OWNER_TEMPLATE_NAME)
    assert winner is not None
    assert result.owner_role_id == str(winner.id)
    assert len(await roles.get_all_active()) == 1


class _BrokenPermissions(MockPermissionRepository):
    async def create(self, permission: Permission) -> Permission:
        raise DuplicateKeyError("E11000 duplicate key")


class _BrokenRoles(MockRoleRepository):
    async def create(self, role: Role) -> Role:  # type: ignore[override]
        raise DuplicateKeyError("E11000 duplicate key")


async def test_a_duplicate_with_no_winner_is_not_swallowed(env: Env) -> None:
    with pytest.raises(DuplicateKeyError):
        await ensure_builtins(_BrokenPermissions("default", env.state), env.roles)

    permission = await env.permissions.create(make_permission(*BUILTIN_TEAM_MANAGE))
    assert permission.id is not None
    with pytest.raises(DuplicateKeyError):
        await ensure_builtins(env.permissions, _BrokenRoles("default", env.state))


async def test_a_role_race_won_by_a_plain_owner_is_a_conflict(env: Env) -> None:
    class Squatted(MockRoleRepository):
        async def create(self, role: Role) -> Role:  # type: ignore[override]
            await super().create(make_role(name=role.name))
            raise DuplicateKeyError("E11000 duplicate key")

    with pytest.raises(BuiltinConflictError):
        await ensure_builtins(env.permissions, Squatted("default", env.state))
