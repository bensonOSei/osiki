from typing import Any

from fastapi.testclient import TestClient

from tests.e2e.conftest import API

ENV_HEADER = "X-Osiki-Environment"

OWN_TEAM = {
    "op": "eq",
    "left": {"ref": "record.team_id"},
    "right": {"ref": "user.team_id"},
}


def _role(
    client: TestClient,
    resource: str = "invoices",
    action: str = "read",
    condition_id: str | None = None,
    headers: dict[str, str] | None = None,
) -> str:
    perm = client.post(
        f"{API}/permissions",
        json={"resource": resource, "action": action},
        headers=headers,
    ).json()
    grant: dict[str, Any] = {"permission_id": perm["id"]}
    if condition_id:
        grant["condition_id"] = condition_id
    role = client.post(
        f"{API}/roles",
        json={"name": f"{resource}-{action}", "grants": [grant]},
        headers=headers,
    ).json()
    role_id: str = role["id"]
    return role_id


def _user_with_role(
    client: TestClient, role_id: str, attributes: dict[str, Any] | None = None
) -> None:
    client.put(f"{API}/tenants/acme", json={"name": "Acme"})
    user_id = client.put(
        f"{API}/users/by-external/user-1", json={"attributes": attributes or {}}
    ).json()["id"]
    response = client.post(
        f"{API}/users/{user_id}/roles",
        json={
            "role_id": role_id,
            "assigned_by": "admin",
            "scope": {"tenant_id": "acme"},
        },
    )
    assert response.status_code == 201


def _filter(client: TestClient, **body: Any) -> dict[str, Any]:
    body.setdefault("user_id", "user-1")
    body.setdefault("resource", "invoices")
    body.setdefault("action", "read")
    body.setdefault("scope", {"tenant_id": "acme"})
    response = client.post(f"{API}/authorization/filter", json=body)
    assert response.status_code == 200
    result: dict[str, Any] = response.json()
    return result


def test_snapshot_etag_and_304(client: TestClient) -> None:
    _role(client)
    response = client.get(f"{API}/snapshot")
    assert response.status_code == 200
    version = response.json()["version"]
    assert response.headers["ETag"] == f'"{version}"'
    assert response.json()["roles"]

    cached = client.get(f"{API}/snapshot", headers={"If-None-Match": f'"{version}"'})
    assert cached.status_code == 304
    assert cached.content == b""
    assert cached.headers["ETag"] == f'"{version}"'

    other = client.get(f"{API}/snapshot", headers={"If-None-Match": '"999999"'})
    assert other.status_code == 200
    assert other.json()["version"] == version


def test_snapshot_version_endpoint_tracks_writes(client: TestClient) -> None:
    before = client.get(f"{API}/snapshot/version").json()["version"]
    _role(client)
    after = client.get(f"{API}/snapshot/version").json()["version"]
    assert after > before
    assert client.get(f"{API}/snapshot").json()["version"] == after


def test_bundle_404_unknown_user(client: TestClient) -> None:
    response = client.get(f"{API}/users/by-external/ghost/bundle")
    assert response.status_code == 404


def test_bundle_contents(client: TestClient) -> None:
    role_id = _role(client)
    _user_with_role(client, role_id, {"team_id": "t1"})
    response = client.get(f"{API}/users/by-external/user-1/bundle")
    assert response.status_code == 200
    bundle = response.json()
    assert bundle["user_id"] == "user-1"
    assert bundle["attributes"] == {"team_id": "t1"}
    assert [a["role_id"] for a in bundle["assignments"]] == [role_id]
    assert bundle["assignments"][0]["scope"] == {"tenant_id": "acme"}


def test_filter_own_team_returns_field_filter(client: TestClient) -> None:
    cond = client.post(
        f"{API}/conditions",
        json={"key": "own_team", "name": "Own team", "expression": OWN_TEAM},
    ).json()
    role_id = _role(client, condition_id=cond["id"])
    _user_with_role(client, role_id, {"team_id": "t1"})
    assert _filter(client) == {
        "mode": "filter",
        "filter": {"field": "team_id", "op": "eq", "value": "t1", "type": "string"},
    }


def test_filter_unconditional_returns_all(client: TestClient) -> None:
    _user_with_role(client, _role(client))
    assert _filter(client) == {"mode": "all", "filter": None}


def test_filter_unknown_user_returns_none(client: TestClient) -> None:
    assert _filter(client, user_id="ghost") == {"mode": "none", "filter": None}


def test_snapshot_env_isolated(client: TestClient) -> None:
    _role(client, headers={ENV_HEADER: "a"})
    in_a = client.get(f"{API}/snapshot", headers={ENV_HEADER: "a"}).json()
    in_b = client.get(f"{API}/snapshot", headers={ENV_HEADER: "b"}).json()
    assert in_a["environment_id"] == "a"
    assert in_b["environment_id"] == "b"
    assert len(in_a["roles"]) == 1
    assert in_b["roles"] == []
