from osiki.decision.models import EndpointEntry, EnvironmentSettings
from osiki.repositories.endpoints.mongodb_endpoint_repository import (
    MongoDBEndpointRepository,
)
from osiki.repositories.environment_state.mongodb_environment_state_repository import (
    MongoDBEnvironmentStateRepository,
)

ENV = "default"


def _repo(
    environment_id: str = ENV,
) -> tuple[MongoDBEndpointRepository, MongoDBEnvironmentStateRepository]:
    state = MongoDBEnvironmentStateRepository(environment_id)
    return MongoDBEndpointRepository(environment_id, state), state


def _entry(permission: str = "invoices:read", path: str = "/invoices") -> EndpointEntry:
    return EndpointEntry(method="GET", path=path, permission=permission)


async def test_record_discovered_upserts_and_updates_last_seen() -> None:
    repo, state = _repo()

    assert await repo.record_discovered([("GET", "/a"), ("GET", "/a")], 10.0) == 1
    assert await repo.record_discovered([("GET", "/a"), ("POST", "/a")], 20.0) == 2

    found = {(d.method, d.path): d for d in await repo.list_discovered()}
    assert len(found) == 2
    assert (found["GET", "/a"].first_seen, found["GET", "/a"].last_seen) == (10.0, 20.0)
    assert found["POST", "/a"].first_seen == 20.0
    assert await state.get_config_version() == 0


async def test_upsert_mapping_creates_replaces_and_bumps() -> None:
    repo, state = _repo()

    created = await repo.upsert_mapping(_entry())
    replaced = await repo.upsert_mapping(_entry("invoices:list"))

    mappings = await repo.list_mappings()
    assert len(mappings) == 1
    assert mappings[0].permission == "invoices:list"
    assert replaced.id == created.id
    assert replaced.updated_at >= created.updated_at
    assert await state.get_config_version() == 2


async def test_delete_mapping_bumps_only_when_present() -> None:
    repo, state = _repo()
    await repo.upsert_mapping(_entry())

    assert await repo.delete_mapping("GET", "/missing") is False
    assert await state.get_config_version() == 1
    assert await repo.delete_mapping("GET", "/invoices") is True
    assert await state.get_config_version() == 2
    assert await repo.list_mappings() == []


async def test_endpoints_are_environment_scoped() -> None:
    repo, _ = _repo()
    other, other_state = _repo("other")
    await repo.upsert_mapping(_entry())
    await repo.record_discovered([("GET", "/a")], 1.0)

    assert await other.list_mappings() == []
    assert await other.list_discovered() == []
    assert await other.delete_mapping("GET", "/invoices") is False
    assert await other_state.get_config_version() == 0


async def test_update_settings_persists_and_bumps() -> None:
    _, state = _repo()
    assert await state.get_settings() == EnvironmentSettings()

    saved = await state.update_settings(EnvironmentSettings(unmapped="allow"))
    assert saved.unmapped == "allow"
    assert (await state.get_settings()).unmapped == "allow"
    assert await state.get_config_version() == 1

    await state.update_settings(EnvironmentSettings(unmapped="deny"))
    assert (await state.get_settings()).unmapped == "deny"
    assert await state.get_config_version() == 2
