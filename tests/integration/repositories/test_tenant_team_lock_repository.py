"""Integration tests for the per-tenant team lock counter."""

from osiki.models.tenant_team_lock import TenantTeamLock
from osiki.repositories.tenant_team_locks.mongodb_tenant_team_lock_repository import (
    MongoDBTenantTeamLockRepository,
)


async def _version(environment_id: str, tenant_id: str) -> int | None:
    lock = await TenantTeamLock.find_one(
        TenantTeamLock.environment_id == environment_id,
        TenantTeamLock.tenant_id == tenant_id,
    )
    return None if lock is None else lock.version


async def test_ensure_creates_the_lock_once_and_never_changes_it() -> None:
    repo = MongoDBTenantTeamLockRepository("default")
    await repo.ensure("acme")
    assert await _version("default", "acme") == 0
    await repo.bump("acme")
    await repo.ensure("acme")
    assert await _version("default", "acme") == 1
    assert await TenantTeamLock.find_all().count() == 1


async def test_bump_increments_and_returns_the_new_version() -> None:
    repo = MongoDBTenantTeamLockRepository("default")
    assert await repo.bump("acme") == 1  # upserts a missing lock
    assert await repo.bump("acme") == 2
    assert await _version("default", "acme") == 2


async def test_locks_are_per_tenant_and_per_environment() -> None:
    await MongoDBTenantTeamLockRepository("default").bump("acme")
    assert await MongoDBTenantTeamLockRepository("default").bump("other") == 1
    assert await MongoDBTenantTeamLockRepository("staging").bump("acme") == 1
    assert await _version("default", "acme") == 1
