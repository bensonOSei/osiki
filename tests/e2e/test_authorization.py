from typing import Any

from fastapi.testclient import TestClient

from tests.e2e.conftest import API


def _check(client: TestClient, **body: Any) -> dict[str, Any]:
    response = client.post(f"{API}/authorization/check", json=body)
    assert response.status_code == 200
    result: dict[str, Any] = response.json()
    return result


def _user(client: TestClient, external_id: str) -> str:
    """Create a user and return its internal id."""
    response = client.post(f"{API}/users", json={"external_id": external_id})
    user_id: str = response.json()["id"]
    return user_id


def _grant(
    client: TestClient,
    user_id: str,
    resource: str,
    action: str,
    scope: dict[str, str] | None = None,
) -> None:
    """Give the user (internal id) a role holding resource:action."""
    perm = client.post(
        f"{API}/permissions", json={"resource": resource, "action": action}
    ).json()
    role = client.post(
        f"{API}/roles",
        json={"name": f"{resource}-{action}", "permission_ids": [perm["id"]]},
    ).json()
    body: dict[str, Any] = {"role_id": role["id"], "assigned_by": "admin"}
    if scope is not None:
        body["scope"] = scope
    response = client.post(f"{API}/users/{user_id}/roles", json=body)
    assert response.status_code == 201


def test_authorization_check_denied(client: TestClient) -> None:
    _user(client, "user-1")
    data = _check(client, user_id="user-1", resource="documents", action="read")
    assert data["allowed"] is False
    assert data["denial_reason"] == "no_permission"


def test_authorization_check_unknown_user(client: TestClient) -> None:
    data = _check(client, user_id="user-1", resource="documents", action="read")
    assert data["allowed"] is False
    assert data["denial_reason"] == "unknown_user"


def test_authorization_check_granted_by_external_id(client: TestClient) -> None:
    user_id = _user(client, "user-1")
    _grant(client, user_id, "documents", "read")

    data = _check(client, user_id="user-1", resource="documents", action="read")
    assert data["allowed"] is True
    assert data["matched_permission"] == "documents:read"


def test_authorization_check_rejects_internal_id(client: TestClient) -> None:
    user_id = _user(client, "user-1")
    _grant(client, user_id, "documents", "read")

    data = _check(client, user_id=user_id, resource="documents", action="read")
    assert data["allowed"] is False
    assert data["denial_reason"] == "unknown_user"


def test_authorization_check_with_scope(client: TestClient) -> None:
    _user(client, "user-1")
    data = _check(
        client,
        user_id="user-1",
        resource="documents",
        action="read",
        scope={"tenant_id": "tenant-1"},
    )
    assert data["allowed"] is False
    assert data["denial_reason"] == "not_tenant_member"


def test_authorization_check_without_scope(client: TestClient) -> None:
    _user(client, "user-1")
    data = _check(client, user_id="user-1", resource="documents", action="write")
    assert data["allowed"] is False
    assert data["denial_reason"] == "no_permission"


def test_tenant_scoped_grant_only_applies_in_its_tenant(client: TestClient) -> None:
    client.put(f"{API}/tenants/t", json={"name": "T"})
    client.put(f"{API}/tenants/u", json={"name": "U"})
    user_id = _user(client, "user-1")
    _grant(client, user_id, "documents", "read", scope={"tenant_id": "t"})
    client.put(f"{API}/tenants/u/members/user-1")

    in_tenant = _check(
        client,
        user_id="user-1",
        resource="documents",
        action="read",
        scope={"tenant_id": "t"},
    )
    assert in_tenant["allowed"] is True

    other_tenant = _check(
        client,
        user_id="user-1",
        resource="documents",
        action="read",
        scope={"tenant_id": "u"},
    )
    assert other_tenant["allowed"] is False
    assert other_tenant["denial_reason"] == "no_permission"

    no_tenant = _check(client, user_id="user-1", resource="documents", action="read")
    assert no_tenant["allowed"] is False


def test_project_wide_grant_requires_tenant_membership(client: TestClient) -> None:
    client.put(f"{API}/tenants/t", json={"name": "T"})
    user_id = _user(client, "user-1")
    _grant(client, user_id, "documents", "read")

    before = _check(
        client,
        user_id="user-1",
        resource="documents",
        action="read",
        scope={"tenant_id": "t"},
    )
    assert before["allowed"] is False
    assert before["denial_reason"] == "not_tenant_member"

    client.put(f"{API}/tenants/t/members/user-1")

    after = _check(
        client,
        user_id="user-1",
        resource="documents",
        action="read",
        scope={"tenant_id": "t"},
    )
    assert after["allowed"] is True
