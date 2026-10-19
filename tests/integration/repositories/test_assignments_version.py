"""The assignments version bumps after every write that changes who can do what."""

from collections.abc import Awaitable, Callable

import pytest
from beanie import PydanticObjectId

from osiki.models.group import Group
from osiki.models.group_role import GroupRole
from osiki.models.user import User
from osiki.models.user_group import UserGroup
from osiki.models.user_role import UserRole
from osiki.repositories.environment_state.mongodb_environment_state_repository import (
    MongoDBEnvironmentStateRepository,
)
from osiki.repositories.group_roles.mongodb_group_role_repository import (
    MongoDBGroupRoleRepository,
)
from osiki.repositories.groups.mongodb_group_repository import MongoDBGroupRepository
from osiki.repositories.tenant_members.mongodb_tenant_member_repository import (
    MongoDBTenantMemberRepository,
)
from osiki.repositories.tenants.mongodb_tenant_repository import (
    MongoDBTenantRepository,
)
from osiki.repositories.user_groups.mongodb_user_group_repository import (
    MongoDBUserGroupRepository,
)
from osiki.repositories.user_roles.mongodb_user_role_repository import (
    MongoDBUserRoleRepository,
)
from osiki.repositories.users.mongodb_user_repository import MongoDBUserRepository
from tests.mocks import make_environment_state

ENV = "default"

State = MongoDBEnvironmentStateRepository
Write = Callable[[State], Awaitable[object]]
Setup = Callable[[State], Awaitable[Write]]


async def _user(state: State) -> User:
    return await MongoDBUserRepository(ENV, state).create(User(external_id="u1"))


async def _group(state: State) -> Group:
    return await MongoDBGroupRepository(ENV, state).create(Group(name="g"))


async def _user_upsert(state: State) -> Write:
    return lambda s: MongoDBUserRepository(ENV, s).upsert_by_external_id(
        "u1", "U", None, None
    )


async def _user_upsert_existing(state: State) -> Write:
    await _user(state)
    return lambda s: MongoDBUserRepository(ENV, s).upsert_by_external_id(
        "u1", "Renamed", None, None
    )


async def _user_create(state: State) -> Write:
    return lambda s: MongoDBUserRepository(ENV, s).create(User(external_id="u2"))


async def _user_update(state: State) -> Write:
    user = await _user(state)
    user.attributes = {"team": "a"}
    return lambda s: MongoDBUserRepository(ENV, s).update(user)


async def _user_deactivate(state: State) -> Write:
    user = await _user(state)
    return lambda s: MongoDBUserRepository(ENV, s).deactivate(str(user.id))


async def _user_reactivate(state: State) -> Write:
    user = await _user(state)
    await MongoDBUserRepository(ENV, state).deactivate(str(user.id))
    return lambda s: MongoDBUserRepository(ENV, s).reactivate(str(user.id))


async def _tenant_upsert(state: State) -> Write:
    return lambda s: MongoDBTenantRepository(ENV, s).upsert("acme", "Acme", {})


async def _member_add(state: State) -> Write:
    return lambda s: MongoDBTenantMemberRepository(ENV, s).add("acme", "u1")


async def _member_remove(state: State) -> Write:
    await MongoDBTenantMemberRepository(ENV, state).add("acme", "u1")
    return lambda s: MongoDBTenantMemberRepository(ENV, s).remove("acme", "u1")


async def _user_role_create(state: State) -> Write:
    return lambda s: MongoDBUserRoleRepository(ENV, s).create(
        UserRole(
            user_id=PydanticObjectId(), role_id=PydanticObjectId(), assigned_by="a"
        )
    )


async def _user_role_revoke(state: State) -> Write:
    assignment = await MongoDBUserRoleRepository(ENV, state).create(
        UserRole(
            user_id=PydanticObjectId(), role_id=PydanticObjectId(), assigned_by="a"
        )
    )
    return lambda s: MongoDBUserRoleRepository(ENV, s).revoke(str(assignment.id))


async def _group_role_create(state: State) -> Write:
    return lambda s: MongoDBGroupRoleRepository(ENV, s).create(
        GroupRole(
            group_id=PydanticObjectId(), role_id=PydanticObjectId(), assigned_by="a"
        )
    )


async def _group_role_revoke(state: State) -> Write:
    assignment = await MongoDBGroupRoleRepository(ENV, state).create(
        GroupRole(
            group_id=PydanticObjectId(), role_id=PydanticObjectId(), assigned_by="a"
        )
    )
    return lambda s: MongoDBGroupRoleRepository(ENV, s).revoke(str(assignment.id))


async def _user_group_create(state: State) -> Write:
    return lambda s: MongoDBUserGroupRepository(ENV, s).create(
        UserGroup(user_id=PydanticObjectId(), group_id=PydanticObjectId(), added_by="a")
    )


async def _user_group_remove(state: State) -> Write:
    membership = await MongoDBUserGroupRepository(ENV, state).create(
        UserGroup(user_id=PydanticObjectId(), group_id=PydanticObjectId(), added_by="a")
    )
    return lambda s: MongoDBUserGroupRepository(ENV, s).remove(str(membership.id))


async def _group_deactivate(state: State) -> Write:
    group = await _group(state)
    return lambda s: MongoDBGroupRepository(ENV, s).deactivate(str(group.id))


async def _group_reactivate(state: State) -> Write:
    group = await _group(state)
    await MongoDBGroupRepository(ENV, state).deactivate(str(group.id))
    return lambda s: MongoDBGroupRepository(ENV, s).reactivate(str(group.id))


@pytest.mark.parametrize(
    "setup",
    [
        _user_upsert,
        _user_upsert_existing,
        _user_create,
        _user_update,
        _user_deactivate,
        _user_reactivate,
        _tenant_upsert,
        _member_add,
        _member_remove,
        _user_role_create,
        _user_role_revoke,
        _group_role_create,
        _group_role_revoke,
        _user_group_create,
        _user_group_remove,
        _group_deactivate,
        _group_reactivate,
    ],
    ids=lambda f: f.__name__.lstrip("_"),
)
async def test_assignments_version_bumps_on_every_assignment_write(
    setup: Setup,
) -> None:
    state = State(ENV)
    write = await setup(state)
    before = await state.get_assignments_version()

    await write(state)

    assert await state.get_assignments_version() > before
    assert await state.get_config_version() == 0


async def test_failed_writes_do_not_bump() -> None:
    state = State(ENV)
    missing = str(PydanticObjectId())
    member = MongoDBTenantMemberRepository(ENV, state)
    await member.add("acme", "u1")
    before = await state.get_assignments_version()

    assert await MongoDBUserRepository(ENV, state).deactivate(missing) is False
    assert await MongoDBUserRepository(ENV, state).reactivate(missing) is False
    assert await member.remove("acme", "ghost") is False
    await member.add("acme", "u1")  # already a member: nothing written
    assert await MongoDBUserRoleRepository(ENV, state).revoke(missing) is False
    assert await MongoDBGroupRoleRepository(ENV, state).revoke(missing) is False
    assert await MongoDBUserGroupRepository(ENV, state).remove(missing) is False
    assert await MongoDBGroupRepository(ENV, state).deactivate(missing) is False
    assert await MongoDBGroupRepository(ENV, state).reactivate(missing) is False

    assert await state.get_assignments_version() == before


async def test_assignments_version_is_zero_when_absent() -> None:
    assert await State(ENV).get_assignments_version() == 0


async def test_bump_assignments_version_returns_the_new_value() -> None:
    state = State(ENV)

    assert await state.bump_assignments_version() == 1
    assert await state.bump_assignments_version() == 2
    assert await state.get_assignments_version() == 2
    assert await state.get_config_version() == 0


async def test_assignments_version_is_scoped_to_its_environment() -> None:
    await State("a").bump_assignments_version()

    assert await State("b").get_assignments_version() == 0


async def test_settings_default_to_deny_unmapped() -> None:
    assert (await State(ENV).get_settings()).unmapped == "deny"


async def test_settings_read_the_stored_policy() -> None:
    state = make_environment_state("stored")
    state.unmapped_policy = "allow"
    await state.insert()

    assert (await State("stored").get_settings()).unmapped == "allow"
    assert await State("stored").get_assignments_version() == 0


async def test_noop_upserts_do_not_bump() -> None:
    state = State(ENV)
    users = MongoDBUserRepository(ENV, state)
    tenants = MongoDBTenantRepository(ENV, state)
    user = await users.upsert_by_external_id("u1", "Kofi", "k@test.com", {"a": 1})
    tenant = await tenants.upsert("acme", "Acme", {"plan": "pro"})
    before = await state.get_assignments_version()

    same_user = await users.upsert_by_external_id("u1", "Kofi", "k@test.com", {"a": 1})
    await users.upsert_by_external_id("u1", None, None, None)
    await users.upsert_by_external_id("u1", "Kofi", None, None)
    same_tenant = await tenants.upsert("acme", "Acme", {"plan": "pro"})

    assert await state.get_assignments_version() == before
    assert same_user.id == user.id and same_user.updated_at == user.updated_at
    assert same_tenant.id == tenant.id
    assert same_tenant.updated_at == tenant.updated_at


@pytest.mark.parametrize(
    "change",
    [
        lambda s: MongoDBUserRepository(ENV, s).upsert_by_external_id(
            "u1", "Ama", None, None
        ),
        lambda s: MongoDBUserRepository(ENV, s).upsert_by_external_id(
            "u1", None, "new@test.com", None
        ),
        lambda s: MongoDBUserRepository(ENV, s).upsert_by_external_id(
            "u1", None, None, {"a": 2}
        ),
        lambda s: MongoDBTenantRepository(ENV, s).upsert("acme", "Acme Ltd", {}),
        lambda s: MongoDBTenantRepository(ENV, s).upsert(
            "acme", "Acme", {"plan": "free"}
        ),
    ],
    ids=["user-name", "user-email", "user-attributes", "tenant-name", "tenant-attrs"],
)
async def test_changed_upserts_still_bump(change: Write) -> None:
    state = State(ENV)
    await MongoDBUserRepository(ENV, state).upsert_by_external_id(
        "u1", "Kofi", "k@test.com", {"a": 1}
    )
    await MongoDBTenantRepository(ENV, state).upsert("acme", "Acme", {"plan": "pro"})
    before = await state.get_assignments_version()

    await change(state)

    assert await state.get_assignments_version() > before


TYPE_ONLY_CHANGES = [
    ({"a": 1}, {"a": True}),
    ({"a": 0}, {"a": False}),
    ({"a": 1}, {"a": 1.0}),
    ({"a": [1]}, {"a": [True]}),
]


@pytest.mark.parametrize(("old", "new"), TYPE_ONLY_CHANGES)
async def test_type_only_attribute_changes_are_saved_and_bump(
    old: dict, new: dict
) -> None:
    state = State(ENV)
    users = MongoDBUserRepository(ENV, state)
    tenants = MongoDBTenantRepository(ENV, state)
    await users.upsert_by_external_id("u1", "Kofi", None, old)
    await tenants.upsert("acme", "Acme", old)
    before = await state.get_assignments_version()

    user = await users.upsert_by_external_id("u1", None, None, new)
    assert await state.get_assignments_version() == before + 1
    tenant = await tenants.upsert("acme", "Acme", new)
    assert await state.get_assignments_version() == before + 2

    for saved in (
        await users.get_by_external_id("u1"),
        await tenants.get_by_external_id("acme"),
        user,
        tenant,
    ):
        assert saved is not None
        ((key, value),) = new.items()
        if isinstance(value, list):
            # The model's list type is list[str | int | float], so it coerces
            # a bool element to int on load; the write and bump still happen.
            assert saved.attributes[key] == value
        else:
            assert type(saved.attributes[key]) is type(value)


async def test_identical_upserts_with_reordered_keys_still_skip() -> None:
    state = State(ENV)
    users = MongoDBUserRepository(ENV, state)
    tenants = MongoDBTenantRepository(ENV, state)
    await users.upsert_by_external_id("u1", "Kofi", None, {"a": 1, "b": [1, 2.5]})
    await tenants.upsert("acme", "Acme", {"a": True, "b": "x"})
    before = await state.get_assignments_version()

    await users.upsert_by_external_id("u1", None, None, {"b": [1, 2.5], "a": 1})
    await tenants.upsert("acme", "Acme", {"b": "x", "a": True})

    assert await state.get_assignments_version() == before
