from fastapi.testclient import TestClient

from tests.e2e.conftest import API

ENV_HEADER = "X-Osiki-Environment"
EXPR = {
    "op": "eq",
    "left": {"ref": "record.owner_id"},
    "right": {"ref": "user.id"},
}


def _create(client: TestClient, key: str = "is_owner", **headers: str) -> dict:
    response = client.post(
        f"{API}/conditions",
        json={"key": key, "name": "Is owner", "expression": EXPR},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_condition(client: TestClient) -> None:
    body = _create(client)

    assert body["key"] == "is_owner"
    assert body["name"] == "Is owner"
    assert body["expression"] == EXPR
    assert body["is_active"] is True

    fetched = client.get(f"{API}/conditions/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["key"] == "is_owner"


def test_get_missing_condition_404(client: TestClient) -> None:
    response = client.get(f"{API}/conditions/507f1f77bcf86cd799439011")
    assert response.status_code == 404


def test_invalid_expression_422_with_path(client: TestClient) -> None:
    response = client.post(
        f"{API}/conditions",
        json={"key": "bad", "name": "Bad", "expression": {"and": [{"nope": 1}]}},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["details"]["path"].startswith("$.and")
    assert body["details"]["message"]


def test_invalid_key_422(client: TestClient) -> None:
    response = client.post(
        f"{API}/conditions",
        json={"key": "Bad Key", "name": "Bad", "expression": EXPR},
    )
    assert response.status_code == 422


def test_duplicate_key_409(client: TestClient) -> None:
    _create(client)
    response = client.post(
        f"{API}/conditions",
        json={"key": "is_owner", "name": "Other", "expression": EXPR},
    )
    assert response.status_code == 409


def test_patch_condition(client: TestClient) -> None:
    created = _create(client)
    new_expr = {"op": "eq", "left": {"ref": "user.id"}, "right": {"value": "u1"}}

    response = client.patch(
        f"{API}/conditions/{created['id']}",
        json={"name": "Renamed", "description": "d", "expression": new_expr},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed"
    assert body["description"] == "d"
    assert body["expression"] == new_expr


def test_patch_invalid_expression_422(client: TestClient) -> None:
    created = _create(client)
    response = client.patch(
        f"{API}/conditions/{created['id']}", json={"expression": {"bogus": 1}}
    )
    assert response.status_code == 422
    assert "path" in response.json()["details"]


def test_patch_missing_404(client: TestClient) -> None:
    response = client.patch(
        f"{API}/conditions/507f1f77bcf86cd799439011", json={"name": "x"}
    )
    assert response.status_code == 404


def test_key_immutable_on_patch(client: TestClient) -> None:
    created = _create(client)

    response = client.patch(
        f"{API}/conditions/{created['id']}", json={"key": "renamed", "name": "N"}
    )

    assert response.status_code == 200
    assert response.json()["key"] == "is_owner"
    assert response.json()["name"] == "N"


def test_delete_condition(client: TestClient) -> None:
    created = _create(client)

    assert client.delete(f"{API}/conditions/{created['id']}").status_code == 204
    listed = client.get(f"{API}/conditions").json()
    assert listed["items"] == []


def test_delete_missing_404(client: TestClient) -> None:
    response = client.delete(f"{API}/conditions/507f1f77bcf86cd799439011")
    assert response.status_code == 404


def test_list_conditions(client: TestClient) -> None:
    _create(client, "c_one")
    _create(client, "c_two")

    response = client.get(f"{API}/conditions", params={"page_size": 10})

    assert response.status_code == 200
    assert sorted(i["key"] for i in response.json()["items"]) == ["c_one", "c_two"]


def test_condition_env_isolated(client: TestClient) -> None:
    created = _create(client, "is_owner", **{ENV_HEADER: "a"})

    in_b = client.get(f"{API}/conditions", headers={ENV_HEADER: "b"})
    assert in_b.json()["items"] == []
    got = client.get(f"{API}/conditions/{created['id']}", headers={ENV_HEADER: "b"})
    assert got.status_code == 404
    # the same key is free in another environment
    _create(client, "is_owner", **{ENV_HEADER: "b"})
