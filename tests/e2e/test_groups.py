from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from tests.e2e.conftest import API

# --- Create Group ---


def test_create_group(client: TestClient) -> None:
    response = client.post(
        f"{API}/groups",
        json={"name": "engineering", "description": "Engineering team"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "engineering"
    assert data["description"] == "Engineering team"
    assert data["is_active"] is True
    assert "id" in data


def test_create_group_minimal(client: TestClient) -> None:
    response = client.post(f"{API}/groups", json={"name": "ops"})
    assert response.status_code == 201
    assert response.json()["description"] is None


def test_create_group_with_metadata(client: TestClient) -> None:
    response = client.post(
        f"{API}/groups",
        json={"name": "sales", "metadata": {"region": "us-east"}},
    )
    assert response.status_code == 201
    assert response.json()["metadata"] == {"region": "us-east"}


def test_create_group_duplicate_name(client: TestClient) -> None:
    client.post(f"{API}/groups", json={"name": "dup-group"})
    response = client.post(f"{API}/groups", json={"name": "dup-group"})
    assert response.status_code == 409
    assert response.json()["error"] == "conflict"


# --- Get Group ---


def test_get_group(client: TestClient) -> None:
    create_resp = client.post(f"{API}/groups", json={"name": "eng"})
    group_id = create_resp.json()["id"]

    response = client.get(f"{API}/groups/{group_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "eng"


def test_get_group_not_found(client: TestClient) -> None:
    fake_id = str(PydanticObjectId())
    response = client.get(f"{API}/groups/{fake_id}")
    assert response.status_code == 404


# --- Update Group ---


def test_update_group_name(client: TestClient) -> None:
    create_resp = client.post(f"{API}/groups", json={"name": "old-name"})
    group_id = create_resp.json()["id"]

    response = client.patch(f"{API}/groups/{group_id}", json={"name": "new-name"})
    assert response.status_code == 200
    assert response.json()["name"] == "new-name"


def test_update_group_description(client: TestClient) -> None:
    create_resp = client.post(f"{API}/groups", json={"name": "eng"})
    group_id = create_resp.json()["id"]

    response = client.patch(f"{API}/groups/{group_id}", json={"description": "updated"})
    assert response.status_code == 200
    assert response.json()["description"] == "updated"


def test_update_group_metadata(client: TestClient) -> None:
    create_resp = client.post(f"{API}/groups", json={"name": "eng"})
    group_id = create_resp.json()["id"]

    response = client.patch(
        f"{API}/groups/{group_id}", json={"metadata": {"level": "senior"}}
    )
    assert response.status_code == 200
    assert response.json()["metadata"] == {"level": "senior"}


def test_update_group_not_found(client: TestClient) -> None:
    fake_id = str(PydanticObjectId())
    response = client.patch(f"{API}/groups/{fake_id}", json={"name": "x"})
    assert response.status_code == 404


# --- Delete Group ---


def test_delete_group(client: TestClient) -> None:
    create_resp = client.post(f"{API}/groups", json={"name": "eng"})
    group_id = create_resp.json()["id"]

    response = client.delete(f"{API}/groups/{group_id}")
    assert response.status_code == 204


def test_delete_group_not_found(client: TestClient) -> None:
    fake_id = str(PydanticObjectId())
    response = client.delete(f"{API}/groups/{fake_id}")
    assert response.status_code == 404


# --- List Groups ---


def test_list_groups_empty(client: TestClient) -> None:
    response = client.get(f"{API}/groups")
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_list_groups(client: TestClient) -> None:
    client.post(f"{API}/groups", json={"name": "g1"})
    client.post(f"{API}/groups", json={"name": "g2"})

    response = client.get(f"{API}/groups")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 2


def test_list_groups_pagination(client: TestClient) -> None:
    for i in range(3):
        client.post(f"{API}/groups", json={"name": f"g{i}"})

    response = client.get(f"{API}/groups", params={"page": 1, "page_size": 2})
    assert len(response.json()["items"]) == 2

    response = client.get(f"{API}/groups", params={"page": 2, "page_size": 2})
    assert len(response.json()["items"]) == 1


# --- Group Role Assignment ---


def test_assign_role_to_group(client: TestClient) -> None:
    group_resp = client.post(f"{API}/groups", json={"name": "eng"})
    group_id = group_resp.json()["id"]
    role_id = str(PydanticObjectId())

    response = client.post(
        f"{API}/groups/{group_id}/roles",
        json={
            "role_id": role_id,
            "assigned_by": "admin",
            "assignment_reason": "team role",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["group_id"] == group_id
    assert data["role_id"] == role_id
    assert data["is_active"] is True


def test_assign_role_to_group_with_scope(client: TestClient) -> None:
    client.put(f"{API}/tenants/t1", json={"name": "T1"})
    group_resp = client.post(f"{API}/groups", json={"name": "eng"})
    group_id = group_resp.json()["id"]
    role_id = str(PydanticObjectId())

    response = client.post(
        f"{API}/groups/{group_id}/roles",
        json={
            "role_id": role_id,
            "assigned_by": "admin",
            "scope": {"tenant_id": "t1", "region": "us-east"},
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["scope"]["tenant_id"] == "t1"
    assert data["scope"]["region"] == "us-east"


def test_group_tenant_scoped_assignment_adds_no_membership(
    client: TestClient,
) -> None:
    client.put(f"{API}/tenants/t", json={"name": "T"})
    group_id = client.post(f"{API}/groups", json={"name": "eng"}).json()["id"]

    response = client.post(
        f"{API}/groups/{group_id}/roles",
        json={
            "role_id": str(PydanticObjectId()),
            "assigned_by": "admin",
            "scope": {"tenant_id": "t"},
        },
    )
    assert response.status_code == 201
    assert client.get(f"{API}/tenants/t/members").json()["items"] == []


def test_group_tenant_scoped_assignment_unknown_tenant_404(
    client: TestClient,
) -> None:
    group_id = client.post(f"{API}/groups", json={"name": "eng"}).json()["id"]
    role_id = str(PydanticObjectId())

    response = client.post(
        f"{API}/groups/{group_id}/roles",
        json={
            "role_id": role_id,
            "assigned_by": "admin",
            "scope": {"tenant_id": "missing"},
        },
    )
    assert response.status_code == 404
    assert client.delete(f"{API}/groups/{group_id}/roles/{role_id}").status_code == 404


def test_assign_role_to_nonexistent_group(client: TestClient) -> None:
    fake_id = str(PydanticObjectId())
    response = client.post(
        f"{API}/groups/{fake_id}/roles",
        json={"role_id": str(PydanticObjectId()), "assigned_by": "admin"},
    )
    assert response.status_code == 404


def test_revoke_role_from_group(client: TestClient) -> None:
    group_resp = client.post(f"{API}/groups", json={"name": "eng"})
    group_id = group_resp.json()["id"]
    role_id = str(PydanticObjectId())

    client.post(
        f"{API}/groups/{group_id}/roles",
        json={"role_id": role_id, "assigned_by": "admin"},
    )

    response = client.delete(f"{API}/groups/{group_id}/roles/{role_id}")
    assert response.status_code == 204


def test_revoke_role_from_group_not_found(client: TestClient) -> None:
    fake_group = str(PydanticObjectId())
    fake_role = str(PydanticObjectId())
    response = client.delete(f"{API}/groups/{fake_group}/roles/{fake_role}")
    assert response.status_code == 404


def test_mutual_exclusion_blocks_group_role_assignment(client: TestClient) -> None:
    initiator, approver = str(PydanticObjectId()), str(PydanticObjectId())
    client.post(
        f"{API}/constraints",
        json={
            "name": "no-dual-signing",
            "type": "mutual_exclusion",
            "config": {"role_ids": [initiator, approver]},
        },
    )
    group_id = client.post(f"{API}/groups", json={"name": "eng"}).json()["id"]
    user_id = client.post(f"{API}/users", json={"external_id": "ext-1"}).json()["id"]
    client.post(
        f"{API}/users/{user_id}/groups",
        json={"group_id": group_id, "added_by": "admin"},
    )
    client.post(
        f"{API}/users/{user_id}/roles",
        json={"role_id": initiator, "assigned_by": "admin"},
    )

    response = client.post(
        f"{API}/groups/{group_id}/roles",
        json={"role_id": approver, "assigned_by": "admin"},
    )
    assert response.status_code == 409
    assert response.json()["details"]["constraint"] == "no-dual-signing"
    assert client.delete(f"{API}/groups/{group_id}/roles/{approver}").status_code == 404


def test_group_role_assignment_without_members_passes_constraints(
    client: TestClient,
) -> None:
    role = str(PydanticObjectId())
    client.post(
        f"{API}/constraints",
        json={
            "name": "max",
            "type": "cardinality",
            "config": {"role_id": role, "max_assignments": 1, "scope_level": "global"},
        },
    )
    group_id = client.post(f"{API}/groups", json={"name": "eng"}).json()["id"]
    response = client.post(
        f"{API}/groups/{group_id}/roles",
        json={"role_id": role, "assigned_by": "admin"},
    )
    assert response.status_code == 201


# --- Revoking a tenant-scoped group role ---


def _reads_docs(client: TestClient, tenant_id: str) -> bool:
    response = client.post(
        f"{API}/authorization/check",
        json={
            "user_id": "ext-1",
            "resource": "docs",
            "action": "read",
            "scope": {"tenant_id": tenant_id},
        },
    )
    assert response.status_code == 200
    return bool(response.json()["allowed"])


def _group_with_member(client: TestClient) -> tuple[str, str]:
    """A group holding ext-1 (member of tenants a and b) and a docs reader role."""
    group_id = client.post(f"{API}/groups", json={"name": "eng"}).json()["id"]
    user_id = client.post(f"{API}/users", json={"external_id": "ext-1"}).json()["id"]
    for tenant in ("a", "b"):
        client.put(f"{API}/tenants/{tenant}", json={"name": tenant})
        client.put(f"{API}/tenants/{tenant}/members/ext-1")
    client.post(
        f"{API}/users/{user_id}/groups",
        json={"group_id": group_id, "added_by": "admin"},
    )
    perm = client.post(
        f"{API}/permissions", json={"resource": "docs", "action": "read"}
    ).json()
    role = client.post(
        f"{API}/roles",
        json={"name": "reader", "grants": [{"permission_id": perm["id"]}]},
    ).json()
    return group_id, role["id"]


def _assign_group(
    client: TestClient, group_id: str, role_id: str, tenant: str | None
) -> int:
    body: dict[str, object] = {"role_id": role_id, "assigned_by": "admin"}
    if tenant is not None:
        body["scope"] = {"tenant_id": tenant}
    return client.post(f"{API}/groups/{group_id}/roles", json=body).status_code


def test_group_revoke_targets_the_named_tenant(client: TestClient) -> None:
    group_id, role_id = _group_with_member(client)
    assert _assign_group(client, group_id, role_id, "a") == 201
    assert _assign_group(client, group_id, role_id, "b") == 201

    url = f"{API}/groups/{group_id}/roles/{role_id}"
    assert client.delete(url, params={"tenant_id": "a"}).status_code == 204

    assert not _reads_docs(client, "a")
    assert _reads_docs(client, "b")
    assert client.delete(url, params={"tenant_id": "a"}).status_code == 404
    assert client.delete(url, params={"tenant_id": "b"}).status_code == 204
    assert not _reads_docs(client, "b")


def test_group_revoke_without_tenant_never_picks_a_tenant(client: TestClient) -> None:
    group_id, role_id = _group_with_member(client)
    assert _assign_group(client, group_id, role_id, "a") == 201

    response = client.delete(f"{API}/groups/{group_id}/roles/{role_id}")

    assert response.status_code == 404
    assert response.json()["details"]["tenant_id"] == ""
    assert _reads_docs(client, "a")


def test_group_revoke_without_tenant_takes_the_project_wide_one(
    client: TestClient,
) -> None:
    group_id, role_id = _group_with_member(client)
    assert _assign_group(client, group_id, role_id, "a") == 201
    assert _assign_group(client, group_id, role_id, None) == 201

    assert client.delete(f"{API}/groups/{group_id}/roles/{role_id}").status_code == 204

    assert _reads_docs(client, "a")
    assert not _reads_docs(client, "b")
