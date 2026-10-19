from fastapi.testclient import TestClient

from tests.e2e.conftest import API

ENV_HEADER = "X-Osiki-Environment"


def test_bootstrap_is_idempotent(client: TestClient) -> None:
    a = client.put(f"{API}/environment/bootstrap").json()
    b = client.put(f"{API}/environment/bootstrap").json()
    assert a == b
    owner = client.get(f"{API}/roles/{a['owner_role_id']}").json()
    assert (owner["name"], owner["is_template"], owner["is_system"]) == (
        "Owner",
        True,
        True,
    )
    assert owner["tenant_id"] is None
    assert owner["grants"] == [
        {"permission_id": a["team_manage_permission_id"], "condition_id": None}
    ]
    assert len(client.get(f"{API}/roles").json()["items"]) == 1
    assert len(client.get(f"{API}/permissions").json()["items"]) == 1


def test_bootstrap_creates_the_built_in_permission(client: TestClient) -> None:
    body = client.put(f"{API}/environment/bootstrap").json()
    perm = client.get(f"{API}/permissions/{body['team_manage_permission_id']}").json()
    assert perm["permission_string"] == "osiki.team:manage"
    assert perm["assignable"] is False


def test_bootstrap_is_per_environment(client: TestClient) -> None:
    a = client.put(f"{API}/environment/bootstrap", headers={ENV_HEADER: "a"}).json()
    b = client.put(f"{API}/environment/bootstrap", headers={ENV_HEADER: "b"}).json()
    assert a["owner_role_id"] != b["owner_role_id"]
    assert client.get(f"{API}/roles").json()["items"] == []


def test_bootstrap_refuses_when_a_plain_owner_role_exists(client: TestClient) -> None:
    client.post(f"{API}/roles", json={"name": "Owner"})
    response = client.put(f"{API}/environment/bootstrap")
    assert response.status_code == 409
    assert "not the built-in template" in response.json()["message"]
    # Nothing was changed for the squatter.
    items = client.get(f"{API}/roles").json()["items"]
    assert [(r["name"], r["is_template"]) for r in items] == [("Owner", False)]


def test_bootstrap_bumps_the_snapshot_version_once(client: TestClient) -> None:
    client.put(f"{API}/environment/bootstrap")
    after_first = client.get(f"{API}/snapshot").json()["version"]
    client.put(f"{API}/environment/bootstrap")
    assert client.get(f"{API}/snapshot").json()["version"] == after_first


def test_owner_template_cannot_be_deleted(client: TestClient) -> None:
    owner = client.put(f"{API}/environment/bootstrap").json()["owner_role_id"]
    assert client.delete(f"{API}/roles/{owner}").status_code == 404
    assert client.get(f"{API}/roles/{owner}").json()["is_active"] is True
