"""Integration tests for MongoDBTenantMemberRepository."""

from osiki.repositories.tenant_members.mongodb_tenant_member_repository import (
    MongoDBTenantMemberRepository,
)


async def test_add_is_idempotent() -> None:
    repo = MongoDBTenantMemberRepository("default")
    await repo.add("t1", "u1")
    await repo.add("t1", "u1")
    assert await repo.members("t1", 0, 10) == ["u1"]


async def test_remove() -> None:
    repo = MongoDBTenantMemberRepository("default")
    await repo.add("t1", "u1")
    assert await repo.remove("t1", "u1") is True
    assert await repo.remove("t1", "u1") is False
    assert await repo.is_member("t1", "u1") is False


async def test_is_member() -> None:
    repo = MongoDBTenantMemberRepository("default")
    await repo.add("t1", "u1")
    assert await repo.is_member("t1", "u1") is True
    assert await repo.is_member("t1", "u2") is False
    assert await repo.is_member("t2", "u1") is False


async def test_tenants_for_user() -> None:
    repo = MongoDBTenantMemberRepository("default")
    await repo.add("t1", "u1")
    await repo.add("t2", "u1")
    await repo.add("t3", "u2")
    assert sorted(await repo.tenants_for_user("u1")) == ["t1", "t2"]
    assert await repo.tenants_for_user("nobody") == []


async def test_members_paginates() -> None:
    repo = MongoDBTenantMemberRepository("default")
    for i in range(5):
        await repo.add("t1", f"u{i}")
    await repo.add("t2", "other")
    page1 = await repo.members("t1", 0, 2)
    page2 = await repo.members("t1", 2, 2)
    page3 = await repo.members("t1", 4, 2)
    assert len(page1) == 2 and len(page2) == 2 and len(page3) == 1
    assert sorted(page1 + page2 + page3) == [f"u{i}" for i in range(5)]


async def test_isolated_by_environment() -> None:
    await MongoDBTenantMemberRepository("a").add("t1", "u1")
    other = MongoDBTenantMemberRepository("b")
    assert await other.is_member("t1", "u1") is False
    assert await other.tenants_for_user("u1") == []
    assert await other.members("t1", 0, 10) == []
    assert await other.remove("t1", "u1") is False
