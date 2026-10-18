"""Integration tests for MongoDBAccessLogRepository."""

from osiki.models.access_log import AccessContext, AccessLog
from osiki.repositories.access_logs.mongodb_access_log_repository import (
    MongoDBAccessLogRepository,
)


async def test_create() -> None:
    repo = MongoDBAccessLogRepository("default")
    log = AccessLog(
        user_id="user-1",
        resource="docs",
        action="read",
        scope={},
        allowed=True,
        latency_ms=10.5,
        cache_hit=False,
        context=AccessContext(),
    )
    result = await repo.create(log)
    assert result.id is not None


async def test_get_by_user() -> None:
    repo = MongoDBAccessLogRepository("default")
    await repo.create(
        AccessLog(
            user_id="access-user-1",
            resource="files",
            action="write",
            scope={},
            allowed=True,
            latency_ms=5.0,
            cache_hit=False,
            context=AccessContext(),
        )
    )
    result = await repo.get_by_user("access-user-1")
    assert len(result) >= 1


async def test_get_denials() -> None:
    repo = MongoDBAccessLogRepository("default")
    await repo.create(
        AccessLog(
            user_id="denied-user",
            resource="secret",
            action="access",
            scope={},
            allowed=False,
            denial_reason="no_permission",
            latency_ms=1.0,
            cache_hit=False,
            context=AccessContext(),
        )
    )
    result = await repo.get_denials()
    assert len(result) >= 1


async def test_get_by_resource() -> None:
    repo = MongoDBAccessLogRepository("default")
    await repo.create(
        AccessLog(
            user_id="user-1",
            resource="dashboard",
            action="view",
            scope={},
            allowed=True,
            latency_ms=2.0,
            cache_hit=True,
            context=AccessContext(),
        )
    )
    result = await repo.get_by_resource("dashboard")
    assert len(result) >= 1


async def test_get_by_resource_with_action() -> None:
    repo = MongoDBAccessLogRepository("default")
    await repo.create(
        AccessLog(
            user_id="user-1",
            resource="api",
            action="read",
            scope={},
            allowed=True,
            latency_ms=1.0,
            cache_hit=False,
            context=AccessContext(),
        )
    )
    await repo.create(
        AccessLog(
            user_id="user-2",
            resource="api",
            action="write",
            scope={},
            allowed=True,
            latency_ms=1.0,
            cache_hit=False,
            context=AccessContext(),
        )
    )
    result = await repo.get_by_resource("api", action="read")
    assert len(result) == 1


async def test_get_recent() -> None:
    repo = MongoDBAccessLogRepository("default")
    for i in range(3):
        await repo.create(
            AccessLog(
                user_id=f"recent-user-{i}",
                resource="api",
                action="call",
                scope={},
                allowed=True,
                latency_ms=10.0,
                cache_hit=False,
                context=AccessContext(),
            )
        )
    result = await repo.get_recent(limit=10)
    assert len(result) >= 3
