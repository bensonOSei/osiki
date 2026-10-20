from osiki.api.actor import Actor
from osiki.services.audit.audit_writer import AuditWriter
from tests.mocks import MockAuditLogRepository


async def test_record_writes_top_level_tenant_and_actor() -> None:
    repo = MockAuditLogRepository("env")
    entry = await AuditWriter(repo).record(
        Actor(type="tenant_user", id="u1"),
        "role.create",
        "role",
        "r1",
        tenant_id="t1",
        before=None,
        after={"name": "Cashier"},
    )
    assert (entry.tenant_id, entry.actor_type, entry.actor_id) == (
        "t1",
        "tenant_user",
        "u1",
    )
    assert entry.changes.after == {"name": "Cashier"}
    assert entry.changes.before is None
    assert (entry.action, entry.target_type, entry.target_id) == (
        "role.create",
        "role",
        "r1",
    )
    assert await repo.get_recent() == [entry]


async def test_record_without_tenant() -> None:
    entry = await AuditWriter(MockAuditLogRepository("env")).record(
        Actor(type="developer", id="d"),
        "x",
        "y",
        "z",
        tenant_id=None,
        before={"a": 1},
        after=None,
    )
    assert entry.tenant_id is None
    assert entry.changes.before == {"a": 1}
