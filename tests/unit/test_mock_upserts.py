"""The mock repositories honour the same type-strict no-op rule as MongoDB."""

import pytest

from tests.mocks import (
    MockEnvironmentStateRepository,
    MockTenantRepository,
    MockUserRepository,
)

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
    state = MockEnvironmentStateRepository("default")
    users = MockUserRepository("default", state)
    tenants = MockTenantRepository("default", state)
    await users.upsert_by_external_id("u1", "Kofi", None, old)
    await tenants.upsert("acme", "Acme", old)
    before = await state.get_assignments_version()

    user = await users.upsert_by_external_id("u1", None, None, new)
    assert await state.get_assignments_version() == before + 1
    tenant = await tenants.upsert("acme", "Acme", new)
    assert await state.get_assignments_version() == before + 2

    for saved in (user, tenant):
        ((key, value),) = new.items()
        assert saved.attributes == new
        if isinstance(value, list):
            assert [type(v) for v in saved.attributes[key]] == [type(v) for v in value]
        else:
            assert type(saved.attributes[key]) is type(value)


async def test_identical_upserts_with_reordered_keys_still_skip() -> None:
    state = MockEnvironmentStateRepository("default")
    users = MockUserRepository("default", state)
    tenants = MockTenantRepository("default", state)
    await users.upsert_by_external_id("u1", "Kofi", None, {"a": 1, "b": [1, 2.5]})
    await tenants.upsert("acme", "Acme", {"a": True, "b": "x"})
    before = await state.get_assignments_version()

    await users.upsert_by_external_id("u1", None, None, {"b": [1, 2.5], "a": 1})
    await tenants.upsert("acme", "Acme", {"b": "x", "a": True})

    assert await state.get_assignments_version() == before
