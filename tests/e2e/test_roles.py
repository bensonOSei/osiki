from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from tests.e2e.conftest import API

# --- Create Role ---


def test_create_role(client: TestClient) -> None:
    response = client.post(
        f"{API}/roles",
        json={"name": "admin", "description": "Administrator role"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "admin"
    assert data["description"] == "Administrator role"
    assert data["is_system"] is False
    assert data["is_active"] is True
    assert data["permission_ids"] == []


def test_create_role_with_permissions(client: TestClient) -> None:
    pid1 = str(PydanticObjectId())
    pid2 = str(PydanticObjectId())

    response = client.post(
        f"{API}/roles",
        json={"name": "editor", "permission_ids": [pid1, pid2]},
    )
    assert response.status_code == 201
    assert set(response.json()["permission_ids"]) == {pid1, pid2}


def test_create_role_with_parent(client: TestClient) -> None:
    parent_resp = client.post(f"{API}/roles", json={"name": "manager"})
    parent_id = parent_resp.json()["id"]

    response = client.post(
        f"{API}/roles",
        json={"name": "team-lead", "parent_role_id": parent_id},
    )
    assert response.status_code == 201
    assert response.json()["parent_role_id"] == parent_id


def test_create_system_role(client: TestClient) -> None:
    response = client.post(
        f"{API}/roles",
        json={"name": "superadmin", "is_system": True},
    )
    assert response.status_code == 201
    assert response.json()["is_system"] is True


def test_create_role_with_metadata(client: TestClient) -> None:
    response = client.post(
        f"{API}/roles",
        json={"name": "viewer", "metadata": {"level": "basic"}},
    )
    assert response.status_code == 201
    assert response.json()["metadata"] == {"level": "basic"}


def test_create_role_duplicate_name(client: TestClient) -> None:
    client.post(f"{API}/roles", json={"name": "dup-role"})
    response = client.post(f"{API}/roles", json={"name": "dup-role"})
    assert response.status_code == 409
    assert response.json()["error"] == "conflict"


# --- Get Role ---


def test_get_role(client: TestClient) -> None:
    create_resp = client.post(f"{API}/roles", json={"name": "admin"})
    role_id = create_resp.json()["id"]

    response = client.get(f"{API}/roles/{role_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "admin"


def test_get_role_not_found(client: TestClient) -> None:
    fake_id = str(PydanticObjectId())
    response = client.get(f"{API}/roles/{fake_id}")
    assert response.status_code == 404


# --- Update Role ---


def test_update_role_name(client: TestClient) -> None:
    create_resp = client.post(f"{API}/roles", json={"name": "old"})
    role_id = create_resp.json()["id"]

    response = client.patch(f"{API}/roles/{role_id}", json={"name": "new"})
    assert response.status_code == 200
    assert response.json()["name"] == "new"


def test_update_role_description(client: TestClient) -> None:
    create_resp = client.post(f"{API}/roles", json={"name": "admin"})
    role_id = create_resp.json()["id"]

    response = client.patch(f"{API}/roles/{role_id}", json={"description": "updated"})
    assert response.status_code == 200
    assert response.json()["description"] == "updated"


def test_update_role_permissions(client: TestClient) -> None:
    create_resp = client.post(f"{API}/roles", json={"name": "admin"})
    role_id = create_resp.json()["id"]
    new_pid = str(PydanticObjectId())

    response = client.patch(
        f"{API}/roles/{role_id}", json={"permission_ids": [new_pid]}
    )
    assert response.status_code == 200
    assert response.json()["permission_ids"] == [new_pid]


def test_update_role_parent(client: TestClient) -> None:
    parent_resp = client.post(f"{API}/roles", json={"name": "parent"})
    parent_id = parent_resp.json()["id"]

    create_resp = client.post(f"{API}/roles", json={"name": "child"})
    role_id = create_resp.json()["id"]

    response = client.patch(
        f"{API}/roles/{role_id}", json={"parent_role_id": parent_id}
    )
    assert response.status_code == 200
    assert response.json()["parent_role_id"] == parent_id


def test_update_role_metadata(client: TestClient) -> None:
    create_resp = client.post(f"{API}/roles", json={"name": "admin"})
    role_id = create_resp.json()["id"]

    response = client.patch(
        f"{API}/roles/{role_id}", json={"metadata": {"priority": "high"}}
    )
    assert response.status_code == 200
    assert response.json()["metadata"] == {"priority": "high"}


def test_update_role_not_found(client: TestClient) -> None:
    fake_id = str(PydanticObjectId())
    response = client.patch(f"{API}/roles/{fake_id}", json={"name": "x"})
    assert response.status_code == 404


# --- Delete Role ---


def test_delete_role(client: TestClient) -> None:
    create_resp = client.post(f"{API}/roles", json={"name": "admin"})
    role_id = create_resp.json()["id"]

    response = client.delete(f"{API}/roles/{role_id}")
    assert response.status_code == 204


def test_delete_role_not_found(client: TestClient) -> None:
    fake_id = str(PydanticObjectId())
    response = client.delete(f"{API}/roles/{fake_id}")
    assert response.status_code == 404


# --- List Roles ---


def test_list_roles_empty(client: TestClient) -> None:
    response = client.get(f"{API}/roles")
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_list_roles(client: TestClient) -> None:
    client.post(f"{API}/roles", json={"name": "r1"})
    client.post(f"{API}/roles", json={"name": "r2"})

    response = client.get(f"{API}/roles")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 2


def test_list_roles_pagination(client: TestClient) -> None:
    for i in range(3):
        client.post(f"{API}/roles", json={"name": f"r{i}"})

    response = client.get(f"{API}/roles", params={"page": 1, "page_size": 2})
    assert len(response.json()["items"]) == 2

    response = client.get(f"{API}/roles", params={"page": 2, "page_size": 2})
    assert len(response.json()["items"]) == 1
