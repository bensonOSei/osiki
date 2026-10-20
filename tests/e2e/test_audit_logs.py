import pytest
from fastapi.testclient import TestClient

from tests.e2e.conftest import API, _audit_log_repos
from tests.mocks import MockAuditLogRepository, make_audit_log

URL = f"{API}/audit-logs"


@pytest.fixture
def seed_audit() -> MockAuditLogRepository:
    repo = MockAuditLogRepository("default")
    for tenant, ts in (("t1", 100.0), ("t2", 200.0), ("t1", 300.0)):
        repo._store(f"{tenant}-{ts}", make_audit_log(tenant_id=tenant, timestamp=ts))
    _audit_log_repos["default"] = repo
    return repo


def test_post_records_with_header_actor(client: TestClient) -> None:
    r = client.post(
        URL,
        headers={"X-Osiki-Actor": "tenant_user:u1"},
        json={
            "action": "invite.create",
            "target_type": "invite",
            "target_id": "i1",
            "tenant_id": "t1",
            "after": {"email": "a@b.c"},
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert (body["actor_id"], body["actor_type"]) == ("u1", "tenant_user")
    assert body["tenant_id"] == "t1"
    assert body["after"] == {"email": "a@b.c"}
    assert body["before"] is None


def test_post_without_header_is_anonymous_developer(client: TestClient) -> None:
    r = client.post(URL, json={"action": "a", "target_type": "b", "target_id": "c"})
    assert r.status_code == 201
    assert (r.json()["actor_type"], r.json()["actor_id"]) == (
        "developer",
        "anonymous",
    )
    assert r.json()["tenant_id"] is None


def test_post_malformed_actor_is_rejected_and_not_recorded(
    client: TestClient,
) -> None:
    r = client.post(
        URL,
        headers={"X-Osiki-Actor": "admin:x"},
        json={"action": "a", "target_type": "b", "target_id": "c"},
    )
    assert r.status_code == 422
    assert r.json()["error"] == "validation_error"
    assert client.get(URL).json()["items"] == []


def test_list_filters_by_tenant_newest_first(
    client: TestClient, seed_audit: MockAuditLogRepository
) -> None:
    body = client.get(URL, params={"tenant_id": "t1"}).json()
    assert [i["tenant_id"] for i in body["items"]] == ["t1", "t1"]
    assert [i["timestamp"] for i in body["items"]] == [300.0, 100.0]


def test_list_without_tenant_returns_everything(
    client: TestClient, seed_audit: MockAuditLogRepository
) -> None:
    items = client.get(URL).json()["items"]
    assert [i["timestamp"] for i in items] == [300.0, 200.0, 100.0]


def test_list_paginates(client: TestClient, seed_audit: MockAuditLogRepository) -> None:
    body = client.get(URL, params={"page": 2, "page_size": 2}).json()
    assert [i["timestamp"] for i in body["items"]] == [100.0]
    assert (body["page"], body["page_size"]) == (2, 2)


def test_list_total_counts_all_pages(
    client: TestClient, seed_audit: MockAuditLogRepository
) -> None:
    body = client.get(URL, params={"page": 1, "page_size": 2}).json()
    assert len(body["items"]) == 2
    assert (body["total"], body["total_pages"]) == (3, 2)
    scoped = client.get(URL, params={"tenant_id": "t1", "page_size": 1}).json()
    assert (scoped["total"], scoped["total_pages"]) == (2, 2)


def test_list_is_environment_scoped(
    client: TestClient, seed_audit: MockAuditLogRepository
) -> None:
    r = client.get(URL, headers={"X-Osiki-Environment": "other"})
    assert r.json()["items"] == []
