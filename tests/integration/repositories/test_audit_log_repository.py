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
