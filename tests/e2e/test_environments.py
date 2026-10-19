from fastapi.testclient import TestClient

from tests.e2e.conftest import API

ENV_HEADER = "X-Osiki-Environment"


def test_missing_header_uses_default_environment(client: TestClient) -> None:
    created = client.post(f"{API}/roles", json={"name": "viewer"})
    assert created.status_code == 201

    response = client.get(f"{API}/roles", headers={ENV_HEADER: "default"})

    assert response.status_code == 200
    assert [r["name"] for r in response.json()["items"]] == ["viewer"]


def test_invalid_environment_header_rejected(client: TestClient) -> None:
    response = client.get(f"{API}/roles", headers={ENV_HEADER: "Bad Env!"})

    assert response.status_code == 422


def test_role_in_env_a_invisible_in_env_b(client: TestClient) -> None:
    created = client.post(
        f"{API}/roles", json={"name": "editor"}, headers={ENV_HEADER: "a"}
    )
    assert created.status_code == 201

    response = client.get(f"{API}/roles", headers={ENV_HEADER: "b"})

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_same_role_name_allowed_in_two_envs(client: TestClient) -> None:
    in_a = client.post(
        f"{API}/roles", json={"name": "editor"}, headers={ENV_HEADER: "a"}
    )
    in_b = client.post(
        f"{API}/roles", json={"name": "editor"}, headers={ENV_HEADER: "b"}
    )

    assert in_a.status_code == 201
    assert in_b.status_code == 201
