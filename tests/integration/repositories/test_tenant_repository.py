"""Integration tests for MongoDBTenantRepository."""

from osiki.repositories.environment_state.mongodb_environment_state_repository import (
    MongoDBEnvironmentStateRepository,
)
from osiki.repositories.tenants.mongodb_tenant_repository import (
    MongoDBTenantRepository,
)


async def test_upsert_creates() -> None:
    repo = MongoDBTenantRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    tenant = await repo.upsert("acme", "Acme", {"tier": "gold"})
    assert tenant.id is not None
    assert tenant.name == "Acme"
    assert tenant.attributes == {"tier": "gold"}


async def test_upsert_updates_existing() -> None:
    repo = MongoDBTenantRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    first = await repo.upsert("acme", "Acme", {})
    second = await repo.upsert("acme", "Acme Inc", {"a": 1})
    assert second.id == first.id
    assert second.name == "Acme Inc"
    assert second.attributes == {"a": 1}
    assert second.created_at == first.created_at


async def test_get_by_external_id() -> None:
    repo = MongoDBTenantRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    await repo.upsert("acme", "Acme", {})
    assert (await repo.get_by_external_id("acme")) is not None
    assert (await repo.get_by_external_id("nope")) is None


async def test_get_by_external_id_scoped_by_environment() -> None:
    await MongoDBTenantRepository("a", MongoDBEnvironmentStateRepository("a")).upsert(
        "acme", "Acme", {}
    )
    assert (
        await MongoDBTenantRepository(
            "b", MongoDBEnvironmentStateRepository("b")
        ).get_by_external_id("acme")
    ) is None


async def test_get_many() -> None:
    repo = MongoDBTenantRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    await repo.upsert("t1", "One", {})
    await repo.upsert("t2", "Two", {})
    await repo.upsert("t3", "Three", {})
    await MongoDBTenantRepository(
        "other", MongoDBEnvironmentStateRepository("other")
    ).upsert("t1", "Elsewhere", {})
    result = await repo.get_many(["t1", "t3", "missing"])
    assert sorted(t.external_id for t in result) == ["t1", "t3"]
    assert {t.name for t in result} == {"One", "Three"}


async def test_inactive_tenant_not_returned() -> None:
    repo = MongoDBTenantRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    tenant = await repo.upsert("gone", "Gone", {})
    tenant.is_active = False
    await tenant.save()
    assert await repo.get_by_external_id("gone") is None
    assert await repo.get_many(["gone"]) == []
