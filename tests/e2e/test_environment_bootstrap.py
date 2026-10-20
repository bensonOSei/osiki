import pytest
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
    resp = client.delete(f"{API}/roles/{owner}")
    assert resp.status_code == 422
    assert resp.json()["message"] == "The built-in Owner template cannot be deleted"
    assert client.get(f"{API}/roles/{owner}").json()["is_active"] is True
    assert client.put(f"{API}/environment/bootstrap").status_code == 200


def test_bootstrap_with_a_deactivated_owner_role_is_409(client: TestClient) -> None:
    rid = client.post(f"{API}/roles", json={"name": "Owner"}).json()["id"]
    assert client.delete(f"{API}/roles/{rid}").status_code == 204

    response = client.put(f"{API}/environment/bootstrap")

    assert response.status_code == 409
    assert "inactive role" in response.json()["message"]


# --- The seeded Owner template stays editable, within limits ---


def _owner(client: TestClient) -> dict[str, str]:
    return _bootstrap_ids(client)


def _bootstrap_ids(client: TestClient) -> dict[str, str]:
    body: dict[str, str] = client.put(f"{API}/environment/bootstrap").json()
    return body


def test_owner_template_cannot_be_renamed(client: TestClient) -> None:
    ids = _owner(client)
    response = client.patch(
        f"{API}/roles/{ids['owner_role_id']}", json={"name": "Chief"}
    )
    assert response.status_code == 422
    assert client.get(f"{API}/roles/{ids['owner_role_id']}").json()["name"] == "Owner"
    assert _bootstrap_ids(client) == ids


def test_owner_template_must_stay_a_template(client: TestClient) -> None:
    ids = _owner(client)
    response = client.patch(
        f"{API}/roles/{ids['owner_role_id']}", json={"is_template": False}
    )
    assert response.status_code == 422
    assert client.get(f"{API}/roles/{ids['owner_role_id']}").json()["is_template"]
    assert _bootstrap_ids(client) == ids


@pytest.mark.parametrize("field", ["permission_ids", "grants"])
def test_owner_template_must_keep_team_manage(client: TestClient, field: str) -> None:
    ids = _owner(client)
    other = client.post(
        f"{API}/permissions", json={"resource": "docs", "action": "read"}
    ).json()["id"]
    value: list[object] = (
        [other] if field == "permission_ids" else [{"permission_id": other}]
    )
    for replacement in ([], value):
        response = client.patch(
            f"{API}/roles/{ids['owner_role_id']}", json={field: replacement}
        )
        assert response.status_code == 422
    manage = ids["team_manage_permission_id"]
    conditional = client.post(
        f"{API}/conditions",
        json={
            "key": "c",
            "name": "c",
            "expression": {
                "op": "eq",
                "left": {"ref": "record.owner_id"},
                "right": {"ref": "user.id"},
            },
        },
    ).json()["id"]
    response = client.patch(
        f"{API}/roles/{ids['owner_role_id']}",
        json={"grants": [{"permission_id": manage, "condition_id": conditional}]},
    )
    assert response.status_code == 422
    grants = client.get(f"{API}/roles/{ids['owner_role_id']}").json()["grants"]
    assert [g["permission_id"] for g in grants] == [manage]


def test_owner_template_allows_adding_a_grant_and_a_description(
    client: TestClient,
) -> None:
    ids = _owner(client)
    other = client.post(
        f"{API}/permissions", json={"resource": "docs", "action": "read"}
    ).json()["id"]
    manage = ids["team_manage_permission_id"]

    response = client.patch(
        f"{API}/roles/{ids['owner_role_id']}",
        json={
            "name": "Owner",
            "is_template": True,
            "description": "Edited",
            "permission_ids": [manage, other],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "Edited"
    assert {g["permission_id"] for g in body["grants"]} == {manage, other}
    assert _bootstrap_ids(client) == ids


def test_other_system_roles_are_not_restricted(client: TestClient) -> None:
    rid = client.post(
        f"{API}/roles", json={"name": "Platform", "is_system": True}
    ).json()["id"]
    response = client.patch(
        f"{API}/roles/{rid}", json={"name": "Renamed", "grants": []}
    )
    assert response.status_code == 200


def test_owner_template_description_only_edit_is_allowed(client: TestClient) -> None:
    ids = _owner(client)
    response = client.patch(
        f"{API}/roles/{ids['owner_role_id']}", json={"description": "Only this"}
    )
    assert response.status_code == 200
    assert [g["permission_id"] for g in response.json()["grants"]] == [
        ids["team_manage_permission_id"]
    ]
