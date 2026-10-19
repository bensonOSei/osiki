from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from tests.e2e.conftest import API

# --- Create Permission ---


def test_create_permission(client: TestClient) -> None:
    response = client.post(
        f"{API}/permissions",
        json={
            "resource": "documents",
            "action": "read",
            "description": "Read documents",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["resource"] == "documents"
    assert data["action"] == "read"
    assert data["description"] == "Read documents"
    assert data["permission_string"] == "documents:read"
    assert data["is_active"] is True


def test_create_permission_minimal(client: TestClient) -> None:
    response = client.post(
        f"{API}/permissions",
        json={"resource": "users", "action": "write"},
    )
    assert response.status_code == 201
    assert response.json()["description"] is None


def test_create_permission_with_metadata(client: TestClient) -> None:
    response = client.post(
        f"{API}/permissions",
        json={
            "resource": "reports",
            "action": "export",
            "metadata": {"category": "analytics"},
        },
    )
    assert response.status_code == 201
    assert response.json()["metadata"] == {"category": "analytics"}


def test_create_permission_duplicate(client: TestClient) -> None:
    client.post(
        f"{API}/permissions",
        json={"resource": "docs", "action": "read"},
    )
    response = client.post(
        f"{API}/permissions",
        json={"resource": "docs", "action": "read"},
    )
    assert response.status_code == 409
    assert response.json()["error"] == "conflict"


# --- Get Permission ---


def test_get_permission(client: TestClient) -> None:
    create_resp = client.post(
        f"{API}/permissions",
        json={"resource": "docs", "action": "read"},
    )
    perm_id = create_resp.json()["id"]

    response = client.get(f"{API}/permissions/{perm_id}")
    assert response.status_code == 200
    assert response.json()["resource"] == "docs"
    assert response.json()["permission_string"] == "docs:read"


def test_get_permission_not_found(client: TestClient) -> None:
    fake_id = str(PydanticObjectId())
    response = client.get(f"{API}/permissions/{fake_id}")
    assert response.status_code == 404


# --- Delete Permission ---


def test_delete_permission(client: TestClient) -> None:
    create_resp = client.post(
        f"{API}/permissions",
        json={"resource": "docs", "action": "read"},
    )
    perm_id = create_resp.json()["id"]

    response = client.delete(f"{API}/permissions/{perm_id}")
    assert response.status_code == 204


def test_delete_permission_not_found(client: TestClient) -> None:
    fake_id = str(PydanticObjectId())
    response = client.delete(f"{API}/permissions/{fake_id}")
    assert response.status_code == 404


# --- List Permissions ---


def test_list_permissions_empty(client: TestClient) -> None:
    response = client.get(f"{API}/permissions")
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_list_permissions(client: TestClient) -> None:
    client.post(f"{API}/permissions", json={"resource": "docs", "action": "read"})
    client.post(f"{API}/permissions", json={"resource": "docs", "action": "write"})

    response = client.get(f"{API}/permissions")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 2


def test_list_permissions_pagination(client: TestClient) -> None:
    for action in ["read", "write", "delete"]:
        client.post(f"{API}/permissions", json={"resource": "docs", "action": action})

    response = client.get(f"{API}/permissions", params={"page": 1, "page_size": 2})
    assert len(response.json()["items"]) == 2

    response = client.get(f"{API}/permissions", params={"page": 2, "page_size": 2})
    assert len(response.json()["items"]) == 1


# --- Effective Permissions ---


def test_get_effective_permissions_user_not_found(client: TestClient) -> None:
    fake_id = str(PydanticObjectId())
    response = client.get(f"{API}/permissions/users/{fake_id}/effective")
    assert response.status_code == 404


def test_get_effective_permissions_empty(client: TestClient) -> None:
    user_resp = client.post(f"{API}/users", json={"external_id": "user-1"})
    user_id = user_resp.json()["id"]

    response = client.get(f"{API}/permissions/users/{user_id}/effective")
    assert response.status_code == 200
    assert response.json() == []


def test_effective_permissions_in_tenant_require_membership(
    client: TestClient,
) -> None:
    client.put(f"{API}/tenants/t", json={"name": "T"})
    user_id = client.post(f"{API}/users", json={"external_id": "ext-1"}).json()["id"]
    perm = client.post(
        f"{API}/permissions", json={"resource": "docs", "action": "read"}
    ).json()
    role = client.post(
        f"{API}/roles", json={"name": "reader", "permission_ids": [perm["id"]]}
    ).json()
    client.post(
        f"{API}/users/{user_id}/roles",
        json={"role_id": role["id"], "assigned_by": "admin"},
    )
    url = f"{API}/permissions/users/{user_id}/effective"

    assert client.get(url).json() == ["docs:read"]

    before = client.get(url, params={"tenant_id": "t"})
    assert before.status_code == 200
    assert before.json() == []

    client.put(f"{API}/tenants/t/members/ext-1")

    after = client.get(url, params={"tenant_id": "t"})
    assert after.status_code == 200
    assert after.json() == ["docs:read"]
