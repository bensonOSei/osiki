"""Integration tests for MongoDBAuditLogRepository."""

from osiki.models.audit_log import AuditContext, AuditLog, Changes
from osiki.repositories.audit_logs.mongodb_audit_log_repository import (
    MongoDBAuditLogRepository,
)


async def test_create() -> None:
    repo = MongoDBAuditLogRepository("default")
    log = AuditLog(
        actor_id="user-1",
        actor_type="user",
        action="create",
        target_type="role",
        target_id="role-1",
        changes=Changes(),
        context=AuditContext(),
    )
    result = await repo.create(log)
    assert result.id is not None


async def test_get_by_actor() -> None:
    repo = MongoDBAuditLogRepository("default")
    await repo.create(
        AuditLog(
            actor_id="user-actor-1",
            actor_type="user",
            action="update",
            target_type="role",
            target_id="role-1",
            changes=Changes(),
            context=AuditContext(),
        )
    )
    result = await repo.get_by_actor("user-actor-1")
    assert len(result) >= 1


async def test_get_by_target() -> None:
    repo = MongoDBAuditLogRepository("default")
    await repo.create(
        AuditLog(
            actor_id="user-1",
            actor_type="user",
            action="delete",
            target_type="permission",
            target_id="perm-target-1",
            changes=Changes(),
            context=AuditContext(),
        )
    )
    result = await repo.get_by_target("permission", "perm-target-1")
    assert len(result) >= 1


async def test_get_by_action() -> None:
    repo = MongoDBAuditLogRepository("default")
    await repo.create(
        AuditLog(
            actor_id="user-1",
            actor_type="user",
            action="specific-action",
            target_type="role",
            target_id="role-1",
            changes=Changes(),
            context=AuditContext(),
        )
    )
    result = await repo.get_by_action("specific-action")
    assert len(result) >= 1


async def test_get_recent() -> None:
    repo = MongoDBAuditLogRepository("default")
    for i in range(3):
        await repo.create(
            AuditLog(
                actor_id=f"user-{i}",
                actor_type="user",
                action="create",
                target_type="role",
                target_id=f"role-{i}",
                changes=Changes(),
                context=AuditContext(),
            )
        )
    result = await repo.get_recent(limit=10)
    assert len(result) >= 3


def _log(tenant_id: str | None, timestamp: float, **kw: str) -> AuditLog:
    return AuditLog(
        actor_id="u",
        actor_type="tenant_user",
        action="x",
        target_type="role",
        target_id="r",
        tenant_id=tenant_id,
        timestamp=timestamp,
        changes=Changes(),
        context=AuditContext(),
    )


async def test_list_filters_tenant_newest_first_and_paginates() -> None:
    repo = MongoDBAuditLogRepository("list-env")
    for tenant, ts in (("t1", 1.0), ("t2", 2.0), ("t1", 3.0), ("t1", 4.0)):
        await repo.create(_log(tenant, ts))
    scoped = await repo.list("t1", skip=0, limit=10)
    assert [a.timestamp for a in scoped] == [4.0, 3.0, 1.0]
    assert [a.timestamp for a in await repo.list("t1", skip=1, limit=1)] == [3.0]
    everything = await repo.list(None, skip=0, limit=10)
    assert [a.timestamp for a in everything] == [4.0, 3.0, 2.0, 1.0]


async def test_list_is_environment_scoped() -> None:
    await MongoDBAuditLogRepository("env-a").create(_log("t1", 1.0))
    assert await MongoDBAuditLogRepository("env-b").list("t1", 0, 10) == []
    assert await MongoDBAuditLogRepository("env-b").list(None, 0, 10) == []


async def test_count_matches_list_filters() -> None:
    repo = MongoDBAuditLogRepository("count-env")
    for tenant, ts in (("t1", 1.0), ("t2", 2.0), ("t1", 3.0)):
        await repo.create(_log(tenant, ts))
    await MongoDBAuditLogRepository("count-other").create(_log("t1", 4.0))
    assert await repo.count("t1") == 2
    assert await repo.count(None) == 3
    assert await repo.count("nobody") == 0
