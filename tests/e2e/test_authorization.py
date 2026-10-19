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


OWN_TEAM = {
    "op": "eq",
    "left": {"ref": "record.team_id"},
    "right": {"ref": "user.team_id"},
}


def _conditional_setup(client: TestClient) -> dict[str, str]:
    """own_team condition, conditional invoices:read, a team-t1 user in acme."""
    cond = client.post(
        f"{API}/conditions",
        json={"key": "own_team", "name": "Own team", "expression": OWN_TEAM},
    ).json()
    perm = client.post(
        f"{API}/permissions", json={"resource": "invoices", "action": "read"}
    ).json()
    role = client.post(
        f"{API}/roles",
        json={
            "name": "clerk",
            "grants": [{"permission_id": perm["id"], "condition_id": cond["id"]}],
        },
    ).json()
    client.put(f"{API}/tenants/acme", json={"name": "Acme"})
    user_id = client.put(
        f"{API}/users/by-external/user-1", json={"attributes": {"team_id": "t1"}}
    ).json()["id"]
    response = client.post(
        f"{API}/users/{user_id}/roles",
        json={
            "role_id": role["id"],
            "assigned_by": "admin",
            "scope": {"tenant_id": "acme"},
        },
    )
    assert response.status_code == 201
    return {"condition_id": cond["id"], "role_id": role["id"]}


def _invoice_check(client: TestClient, record: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "user_id": "user-1",
        "resource": "invoices",
        "action": "read",
        "scope": {"tenant_id": "acme"},
    }
    if record is not None:
        body["record"] = record
    return _check(client, **body)


def test_check_with_record_and_condition(client: TestClient) -> None:
    _conditional_setup(client)

    same_team = _invoice_check(client, {"team_id": "t1"})
    assert same_team["allowed"] is True
    assert same_team["condition"] == "own_team"
    assert same_team["matched_permission"] == "invoices:read"
    assert same_team["matched_via"] == "direct"

    other_team = _invoice_check(client, {"team_id": "t2"})
    assert other_team["allowed"] is False
    assert other_team["denial_reason"] == "condition_failed"
    assert other_team["condition"] is None

    no_record = _invoice_check(client)
    assert no_record["allowed"] is False
    assert no_record["denial_reason"] == "record_required"


def test_deactivated_role_denies_after_cached_allow(client: TestClient) -> None:
    ids = _conditional_setup(client)
    assert _invoice_check(client, {"team_id": "t1"})["allowed"] is True

    assert client.delete(f"{API}/roles/{ids['role_id']}").status_code == 204

    after = _invoice_check(client, {"team_id": "t1"})
    assert after["allowed"] is False
    assert after["denial_reason"] == "no_permission"


def test_config_write_after_a_check_takes_effect(client: TestClient) -> None:
    user_id = _user(client, "user-1")
    _grant(client, user_id, "documents", "read")
    assert _check(client, user_id="user-1", resource="documents", action="read")[
        "allowed"
    ]

    role_id = client.get(f"{API}/roles").json()["items"][0]["id"]
    client.patch(f"{API}/roles/{role_id}", json={"grants": []})

    after = _check(client, user_id="user-1", resource="documents", action="read")
    assert after["allowed"] is False
    assert after["denial_reason"] == "no_permission"


def test_deleted_group_stops_granting(client: TestClient) -> None:
    perm = client.post(
        f"{API}/permissions", json={"resource": "documents", "action": "read"}
    ).json()
    role = client.post(
        f"{API}/roles", json={"name": "reader", "permission_ids": [perm["id"]]}
    ).json()
    group = client.post(f"{API}/groups", json={"name": "readers"}).json()
    client.post(
        f"{API}/groups/{group['id']}/roles",
        json={"role_id": role["id"], "assigned_by": "admin"},
    )
    user_id = _user(client, "user-1")
    client.post(
        f"{API}/users/{user_id}/groups",
        json={"group_id": group["id"], "added_by": "admin"},
    )
    before = _check(client, user_id="user-1", resource="documents", action="read")
    assert before["allowed"] is True
    assert before["matched_via"] == "group"

    assert client.delete(f"{API}/groups/{group['id']}").status_code == 204

    after = _check(client, user_id="user-1", resource="documents", action="read")
    assert after["allowed"] is False
    assert after["denial_reason"] == "no_permission"
