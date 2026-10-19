from beanie import PydanticObjectId
from fastapi.testclient import TestClient
from httpx import Response

from tests.e2e.conftest import API

# --- Create User ---


def test_create_user(client: TestClient) -> None:
    response = client.post(
        f"{API}/users",
        json={"external_id": "user-1", "email": "user@test.com"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["external_id"] == "user-1"
    assert data["email"] == "user@test.com"
    assert data["is_active"] is True
    assert "id" in data


def test_create_user_minimal(client: TestClient) -> None:
    response = client.post(
        f"{API}/users",
        json={"external_id": "user-2"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["external_id"] == "user-2"
    assert data["email"] is None


def test_create_user_with_metadata(client: TestClient) -> None:
    response = client.post(
        f"{API}/users",
        json={
            "external_id": "user-3",
            "metadata": {"department": "engineering"},
        },
    )
    assert response.status_code == 201
    assert response.json()["metadata"] == {"department": "engineering"}


def test_create_user_duplicate_external_id(client: TestClient) -> None:
    client.post(f"{API}/users", json={"external_id": "dup-user"})
    response = client.post(f"{API}/users", json={"external_id": "dup-user"})
    assert response.status_code == 409
    data = response.json()
    assert data["error"] == "conflict"
    assert "external_id" in data["details"]


# --- Get User ---


def test_get_user(client: TestClient) -> None:
    create_resp = client.post(f"{API}/users", json={"external_id": "user-1"})
    user_id = create_resp.json()["id"]

    response = client.get(f"{API}/users/{user_id}")
    assert response.status_code == 200
    assert response.json()["external_id"] == "user-1"


def test_get_user_not_found(client: TestClient) -> None:
    fake_id = str(PydanticObjectId())
    response = client.get(f"{API}/users/{fake_id}")
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


# --- Update User ---


def test_update_user_email(client: TestClient) -> None:
    create_resp = client.post(f"{API}/users", json={"external_id": "user-1"})
    user_id = create_resp.json()["id"]

    response = client.patch(
        f"{API}/users/{user_id}",
        json={"email": "new@test.com"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == "new@test.com"


def test_update_user_metadata(client: TestClient) -> None:
    create_resp = client.post(f"{API}/users", json={"external_id": "user-1"})
    user_id = create_resp.json()["id"]

    response = client.patch(
        f"{API}/users/{user_id}",
        json={"metadata": {"role": "admin"}},
    )
    assert response.status_code == 200
    assert response.json()["metadata"] == {"role": "admin"}


def test_update_user_not_found(client: TestClient) -> None:
    fake_id = str(PydanticObjectId())
    response = client.patch(f"{API}/users/{fake_id}", json={"email": "x@test.com"})
    assert response.status_code == 404


# --- Delete User ---


def test_delete_user(client: TestClient) -> None:
    create_resp = client.post(f"{API}/users", json={"external_id": "user-1"})
    user_id = create_resp.json()["id"]

    response = client.delete(f"{API}/users/{user_id}")
    assert response.status_code == 204


def test_delete_user_not_found(client: TestClient) -> None:
    fake_id = str(PydanticObjectId())
    response = client.delete(f"{API}/users/{fake_id}")
    assert response.status_code == 404


# --- List Users ---


def test_list_users_empty(client: TestClient) -> None:
    response = client.get(f"{API}/users")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


def test_list_users(client: TestClient) -> None:
    client.post(f"{API}/users", json={"external_id": "u1"})
    client.post(f"{API}/users", json={"external_id": "u2"})

    response = client.get(f"{API}/users")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 2


def test_list_users_pagination(client: TestClient) -> None:
    for i in range(3):
        client.post(f"{API}/users", json={"external_id": f"u{i}"})

    response = client.get(f"{API}/users", params={"page": 1, "page_size": 2})
    assert response.status_code == 200
    assert len(response.json()["items"]) == 2

    response = client.get(f"{API}/users", params={"page": 2, "page_size": 2})
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


# --- User Role Assignment ---


def test_assign_role_to_user(client: TestClient) -> None:
    user_resp = client.post(f"{API}/users", json={"external_id": "user-1"})
    user_id = user_resp.json()["id"]
    role_id = str(PydanticObjectId())

    response = client.post(
        f"{API}/users/{user_id}/roles",
        json={
            "role_id": role_id,
            "assigned_by": "admin",
            "assignment_reason": "test",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["user_id"] == user_id
    assert data["role_id"] == role_id
    assert data["assigned_by"] == "admin"
    assert data["is_active"] is True


def test_assign_role_to_user_with_scope(client: TestClient) -> None:
    client.put(f"{API}/tenants/tenant-1", json={"name": "Tenant 1"})
    user_resp = client.post(f"{API}/users", json={"external_id": "user-1"})
    user_id = user_resp.json()["id"]
    client.put(f"{API}/tenants/tenant-1/members/user-1")
    role_id = str(PydanticObjectId())

    response = client.post(
        f"{API}/users/{user_id}/roles",
        json={
            "role_id": role_id,
            "assigned_by": "admin",
            "scope": {"tenant_id": "tenant-1"},
        },
    )
    assert response.status_code == 201
    assert response.json()["scope"]["tenant_id"] == "tenant-1"


def test_tenant_scoped_assignment_requires_membership(client: TestClient) -> None:
    client.put(f"{API}/tenants/t", json={"name": "T"})
    user_resp = client.post(f"{API}/users", json={"external_id": "ext-1"})
    user_id = user_resp.json()["id"]
    role_id = str(PydanticObjectId())

    response = client.post(
        f"{API}/users/{user_id}/roles",
        json={"role_id": role_id, "assigned_by": "admin", "scope": {"tenant_id": "t"}},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["message"] == "User is not a member of this tenant"
    assert body["details"] == {"tenant_id": "t", "hint": "add tenant membership first"}
    # Nothing was written: no membership and no assignment.
    assert client.get(f"{API}/tenants/t/members").json()["items"] == []
    revoke = client.delete(f"{API}/users/{user_id}/roles/{role_id}?tenant_id=t")
    assert revoke.status_code == 404


def test_tenant_scoped_assignment_after_membership(client: TestClient) -> None:
    client.put(f"{API}/tenants/t", json={"name": "T"})
    user_resp = client.post(f"{API}/users", json={"external_id": "ext-1"})
    user_id = user_resp.json()["id"]
    assert client.put(f"{API}/tenants/t/members/ext-1").status_code == 204

    response = client.post(
        f"{API}/users/{user_id}/roles",
        json={
            "role_id": str(PydanticObjectId()),
            "assigned_by": "admin",
            "scope": {"tenant_id": "t"},
        },
    )
    assert response.status_code == 201
    assert response.json()["scope"]["tenant_id"] == "t"
    assert client.get(f"{API}/tenants/t/members").json()["items"] == ["ext-1"]


def test_unscoped_assignment_adds_no_membership(client: TestClient) -> None:
    client.put(f"{API}/tenants/t", json={"name": "T"})
    user_resp = client.post(f"{API}/users", json={"external_id": "ext-1"})
    user_id = user_resp.json()["id"]

    response = client.post(
        f"{API}/users/{user_id}/roles",
        json={"role_id": str(PydanticObjectId()), "assigned_by": "admin"},
    )
    assert response.status_code == 201
    assert client.get(f"{API}/tenants/t/members").json()["items"] == []


def test_tenant_scoped_assignment_unknown_tenant_404(client: TestClient) -> None:
    user_resp = client.post(f"{API}/users", json={"external_id": "ext-1"})
    user_id = user_resp.json()["id"]
    role_id = str(PydanticObjectId())

    response = client.post(
        f"{API}/users/{user_id}/roles",
        json={
            "role_id": role_id,
            "assigned_by": "admin",
            "scope": {"tenant_id": "missing"},
        },
    )
    assert response.status_code == 404
    assert client.get(f"{API}/tenants/missing/members").json()["items"] == []
    # No assignment was created, so there is nothing to revoke.
    assert client.delete(f"{API}/users/{user_id}/roles/{role_id}").status_code == 404


def test_assign_role_to_nonexistent_user(client: TestClient) -> None:
    fake_id = str(PydanticObjectId())
    response = client.post(
        f"{API}/users/{fake_id}/roles",
        json={"role_id": str(PydanticObjectId()), "assigned_by": "admin"},
    )
    assert response.status_code == 404


def test_revoke_role_from_user(client: TestClient) -> None:
    user_resp = client.post(f"{API}/users", json={"external_id": "user-1"})
    user_id = user_resp.json()["id"]
    role_id = str(PydanticObjectId())

    client.post(
        f"{API}/users/{user_id}/roles",
        json={"role_id": role_id, "assigned_by": "admin"},
    )

    response = client.delete(f"{API}/users/{user_id}/roles/{role_id}")
    assert response.status_code == 204


def test_revoke_role_not_found(client: TestClient) -> None:
    fake_user = str(PydanticObjectId())
    fake_role = str(PydanticObjectId())
    response = client.delete(f"{API}/users/{fake_user}/roles/{fake_role}")
    assert response.status_code == 404


# --- User Group Membership ---


def test_add_user_to_group(client: TestClient) -> None:
    user_resp = client.post(f"{API}/users", json={"external_id": "user-1"})
    user_id = user_resp.json()["id"]
    group_id = str(PydanticObjectId())

    response = client.post(
        f"{API}/users/{user_id}/groups",
        json={"group_id": group_id, "added_by": "admin"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["user_id"] == user_id
    assert data["group_id"] == group_id
    assert data["is_active"] is True


def test_add_user_to_group_with_membership_type(client: TestClient) -> None:
    user_resp = client.post(f"{API}/users", json={"external_id": "user-1"})
    user_id = user_resp.json()["id"]
    group_id = str(PydanticObjectId())

    response = client.post(
        f"{API}/users/{user_id}/groups",
        json={
            "group_id": group_id,
            "added_by": "admin",
            "membership_type": "owner",
        },
    )
    assert response.status_code == 201
    assert response.json()["membership_type"] == "owner"


def test_add_nonexistent_user_to_group(client: TestClient) -> None:
    fake_id = str(PydanticObjectId())
    response = client.post(
        f"{API}/users/{fake_id}/groups",
        json={"group_id": str(PydanticObjectId()), "added_by": "admin"},
    )
    assert response.status_code == 404


def test_remove_user_from_group(client: TestClient) -> None:
    user_resp = client.post(f"{API}/users", json={"external_id": "user-1"})
    user_id = user_resp.json()["id"]
    group_id = str(PydanticObjectId())

    client.post(
        f"{API}/users/{user_id}/groups",
        json={"group_id": group_id, "added_by": "admin"},
    )

    response = client.delete(f"{API}/users/{user_id}/groups/{group_id}")
    assert response.status_code == 204


def test_remove_user_from_group_not_found(client: TestClient) -> None:
    fake_user = str(PydanticObjectId())
    fake_group = str(PydanticObjectId())
    response = client.delete(f"{API}/users/{fake_user}/groups/{fake_group}")
    assert response.status_code == 404


# --- Constraint enforcement ---

ENV_HEADER = "X-Osiki-Environment"


def _constraint(client: TestClient, body: dict, **headers: str) -> None:
    resp = client.post(f"{API}/constraints", json=body, headers=headers)
    assert resp.status_code == 201, resp.text


def _make_user(client: TestClient, external_id: str, **headers: str) -> str:
    resp = client.post(
        f"{API}/users", json={"external_id": external_id}, headers=headers
    )
    return str(resp.json()["id"])


def _assign(
    client: TestClient, user_id: str, role_id: str, scope: dict | None = None, **h: str
) -> Response:
    body: dict = {"role_id": role_id, "assigned_by": "admin"}
    if scope:
        body["scope"] = scope
    return client.post(f"{API}/users/{user_id}/roles", json=body, headers=h)


def test_mutual_exclusion_blocks_direct_assignment(client: TestClient) -> None:
    initiator, approver = str(PydanticObjectId()), str(PydanticObjectId())
    _constraint(
        client,
        {
            "name": "no-dual-signing",
            "type": "mutual_exclusion",
            "config": {"role_ids": [initiator, approver]},
        },
    )
    user_id = _make_user(client, "ext-1")
    assert _assign(client, user_id, initiator).status_code == 201

    response = _assign(client, user_id, approver)
    assert response.status_code == 409
    assert response.json()["details"] == {
        "constraint": "no-dual-signing",
        "reason": "User already has a mutually exclusive role",
    }
    # The violating assignment was not written.
    assert client.delete(f"{API}/users/{user_id}/roles/{approver}").status_code == 404


def test_constraint_checked_for_tenant_member(client: TestClient) -> None:
    client.put(f"{API}/tenants/t", json={"name": "T"})
    initiator, approver = str(PydanticObjectId()), str(PydanticObjectId())
    _constraint(
        client,
        {
            "name": "x",
            "type": "mutual_exclusion",
            "config": {"role_ids": [initiator, approver]},
        },
    )
    user_id = _make_user(client, "ext-1")
    client.put(f"{API}/tenants/t/members/ext-1")
    assert _assign(client, user_id, initiator).status_code == 201

    response = _assign(client, user_id, approver, {"tenant_id": "t"})
    assert response.status_code == 409
    assert response.json()["details"]["constraint"] == "x"
    assert client.get(f"{API}/tenants/t/members").json()["items"] == ["ext-1"]


def test_cardinality_per_tenant_counts_only_this_env(client: TestClient) -> None:
    role = str(PydanticObjectId())
    body = {
        "name": "one-admin",
        "type": "cardinality",
        "config": {"role_id": role, "max_assignments": 1, "scope_level": "per_tenant"},
    }
    for env in ("a", "b"):
        _constraint(client, body, **{ENV_HEADER: env})
        client.put(f"{API}/tenants/t", json={"name": "T"}, headers={ENV_HEADER: env})
    scope = {"tenant_id": "t"}

    u1 = _make_user(client, "u1", **{ENV_HEADER: "a"})
    u2 = _make_user(client, "u2", **{ENV_HEADER: "a"})
    u3 = _make_user(client, "u3", **{ENV_HEADER: "b"})
    for env, external_id in (("a", "u1"), ("a", "u2"), ("b", "u3")):
        client.put(f"{API}/tenants/t/members/{external_id}", headers={ENV_HEADER: env})

    assert _assign(client, u1, role, scope, **{ENV_HEADER: "a"}).status_code == 201
    # Env a is full for tenant t; env b has its own count.
    blocked = _assign(client, u2, role, scope, **{ENV_HEADER: "a"})
    assert blocked.status_code == 409
    assert blocked.json()["details"]["constraint"] == "one-admin"
    assert _assign(client, u3, role, scope, **{ENV_HEADER: "b"}).status_code == 201


def test_prerequisite_blocks_assignment(client: TestClient) -> None:
    editor, viewer = str(PydanticObjectId()), str(PydanticObjectId())
    _constraint(
        client,
        {
            "name": "editor-requires-viewer",
            "type": "prerequisite",
            "config": {"role_id": editor, "requires_role_id": viewer},
        },
    )
    user_id = _make_user(client, "ext-1")

    response = _assign(client, user_id, editor)
    assert response.status_code == 409
    assert response.json()["details"]["reason"] == "Prerequisite role not assigned"

    assert _assign(client, user_id, viewer).status_code == 201
    assert _assign(client, user_id, editor).status_code == 201


def test_mutual_exclusion_blocks_joining_group(client: TestClient) -> None:
    initiator, approver = str(PydanticObjectId()), str(PydanticObjectId())
    _constraint(
        client,
        {
            "name": "no-dual-signing",
            "type": "mutual_exclusion",
            "config": {"role_ids": [initiator, approver]},
        },
    )
    group_id = client.post(f"{API}/groups", json={"name": "approvers"}).json()["id"]
    assert (
        client.post(
            f"{API}/groups/{group_id}/roles",
            json={"role_id": approver, "assigned_by": "admin"},
        ).status_code
        == 201
    )
    user_id = _make_user(client, "ext-1")
    assert _assign(client, user_id, initiator).status_code == 201

    response = client.post(
        f"{API}/users/{user_id}/groups",
        json={"group_id": group_id, "added_by": "admin"},
    )
    assert response.status_code == 409
    assert response.json()["details"]["constraint"] == "no-dual-signing"
    assert client.delete(f"{API}/users/{user_id}/groups/{group_id}").status_code == 404


def test_joining_group_without_violation_succeeds(client: TestClient) -> None:
    group_id = client.post(f"{API}/groups", json={"name": "g"}).json()["id"]
    client.post(
        f"{API}/groups/{group_id}/roles",
        json={"role_id": str(PydanticObjectId()), "assigned_by": "admin"},
    )
    user_id = _make_user(client, "ext-1")
    response = client.post(
        f"{API}/users/{user_id}/groups",
        json={"group_id": group_id, "added_by": "admin"},
    )
    assert response.status_code == 201
