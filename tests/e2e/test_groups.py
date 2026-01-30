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
