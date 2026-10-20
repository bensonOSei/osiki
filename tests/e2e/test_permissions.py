import pytest
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
    response = client.get(f"{API}/permissions/users/nobody/effective")
    assert response.status_code == 404


def test_get_effective_permissions_rejects_internal_id(client: TestClient) -> None:
    user_id = client.post(f"{API}/users", json={"external_id": "ext-1"}).json()["id"]

    response = client.get(f"{API}/permissions/users/{user_id}/effective")
    assert response.status_code == 404


def test_get_effective_permissions_empty(client: TestClient) -> None:
    client.post(f"{API}/users", json={"external_id": "user-1"})

    response = client.get(f"{API}/permissions/users/user-1/effective")
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
    url = f"{API}/permissions/users/ext-1/effective"
    grant = {"permission": "docs:read", "condition": None, "via": "direct"}

    assert client.get(url).json() == [grant]

    before = client.get(url, params={"tenant_id": "t"})
    assert before.status_code == 200
    assert before.json() == []

    client.put(f"{API}/tenants/t/members/ext-1")

    after = client.get(url, params={"tenant_id": "t"})
    assert after.status_code == 200
    assert after.json() == [grant]


def test_effective_permissions_report_conditions_and_groups(
    client: TestClient,
) -> None:
    cond = client.post(
        f"{API}/conditions",
        json={
            "key": "own_team",
            "name": "Own team",
            "expression": {
                "op": "eq",
                "left": {"ref": "record.team_id"},
                "right": {"ref": "user.team_id"},
            },
        },
    ).json()
    perm = client.post(
        f"{API}/permissions", json={"resource": "invoices", "action": "read"}
    ).json()
    role = client.post(
        f"{API}/roles",
        json={
            "name": "clerk",
            "grants": [{"permission_id": perm["id"], "condition_id": cond["id"]}],
        },
    ).json()
    group = client.post(f"{API}/groups", json={"name": "clerks"}).json()
    client.post(
        f"{API}/groups/{group['id']}/roles",
        json={"role_id": role["id"], "assigned_by": "admin"},
    )
    user_id = client.post(f"{API}/users", json={"external_id": "ext-1"}).json()["id"]
    client.post(
        f"{API}/users/{user_id}/groups",
        json={"group_id": group["id"], "added_by": "admin"},
    )

    response = client.get(f"{API}/permissions/users/ext-1/effective")

    assert response.json() == [
        {"permission": "invoices:read", "condition": "own_team", "via": "group"}
    ]


# --- Resource and action validation ---


@pytest.mark.parametrize(
    "body",
    [
        {"resource": "", "action": "read"},
        {"resource": "docs", "action": ""},
        {"resource": "docs:x", "action": "read"},
        {"resource": "docs", "action": "read:all"},
        {"resource": ":", "action": "read"},
    ],
)
def test_create_permission_rejects_empty_or_colon(
    client: TestClient, body: dict[str, str]
) -> None:
    response = client.post(f"{API}/permissions", json=body)
    assert response.status_code == 422
    assert client.get(f"{API}/permissions").json()["items"] == []


def test_create_permission_allows_wildcards(client: TestClient) -> None:
    response = client.post(f"{API}/permissions", json={"resource": "*", "action": "*"})
    assert response.status_code == 201
    assert response.json()["permission_string"] == "*:*"


# --- Reserved built-ins and assignable ---


def _bootstrap(client: TestClient, **headers: str) -> dict[str, str]:
    response = client.put(f"{API}/environment/bootstrap", headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, str] = response.json()
    return body


@pytest.mark.parametrize("resource", ["osiki.team", "osiki.anything", "osiki.a.b"])
def test_reserved_prefix_refused(client: TestClient, resource: str) -> None:
    response = client.post(
        f"{API}/permissions", json={"resource": resource, "action": "x"}
    )
    assert response.status_code == 422
    assert response.json()["details"] == {"resource": resource}
    assert client.get(f"{API}/permissions").json()["items"] == []


def test_prefix_lookalikes_are_not_reserved(client: TestClient) -> None:
    for resource in ("osiki", "osikix.team", "my.osiki.team"):
        response = client.post(
            f"{API}/permissions", json={"resource": resource, "action": "x"}
        )
        assert response.status_code == 201, resource


def test_permissions_default_to_not_assignable(client: TestClient) -> None:
    created = client.post(
        f"{API}/permissions", json={"resource": "invoices", "action": "read"}
    ).json()
    assert created["assignable"] is False
    assert (
        client.get(f"{API}/permissions/{created['id']}").json()["assignable"] is False
    )


def test_builtin_cannot_be_marked_assignable(client: TestClient) -> None:
    pid = _bootstrap(client)["team_manage_permission_id"]
    response = client.patch(f"{API}/permissions/{pid}", json={"assignable": True})
    assert response.status_code == 422
    assert response.json()["details"] == {"permission_id": pid}
    assert client.get(f"{API}/permissions/{pid}").json()["assignable"] is False


def test_builtin_can_be_patched_to_not_assignable(client: TestClient) -> None:
    pid = _bootstrap(client)["team_manage_permission_id"]
    response = client.patch(
        f"{API}/permissions/{pid}", json={"assignable": False, "description": "d"}
    )
    assert response.status_code == 200
    assert response.json()["description"] == "d"


def test_builtin_cannot_be_deleted(client: TestClient) -> None:
    pid = _bootstrap(client)["team_manage_permission_id"]
    assert client.delete(f"{API}/permissions/{pid}").status_code == 422
    assert client.get(f"{API}/permissions/{pid}").json()["is_active"] is True
    # Bootstrap keeps working, so the built-in was not left deactivated.
    assert _bootstrap(client)["team_manage_permission_id"] == pid


def test_mark_assignable_and_back(client: TestClient) -> None:
    pid = client.post(
        f"{API}/permissions", json={"resource": "invoices", "action": "read"}
    ).json()["id"]
    on = client.patch(f"{API}/permissions/{pid}", json={"assignable": True})
    assert on.status_code == 200
    assert on.json()["assignable"] is True
    assert client.get(f"{API}/permissions/{pid}").json()["assignable"] is True
    off = client.patch(f"{API}/permissions/{pid}", json={"assignable": False})
    assert off.json()["assignable"] is False


def test_patch_description_leaves_assignable_alone(client: TestClient) -> None:
    pid = client.post(
        f"{API}/permissions", json={"resource": "invoices", "action": "read"}
    ).json()["id"]
    client.patch(f"{API}/permissions/{pid}", json={"assignable": True})
    body = client.patch(
        f"{API}/permissions/{pid}", json={"description": "Read invoices"}
    ).json()
    assert body["assignable"] is True
    assert body["description"] == "Read invoices"


def test_patch_empty_body_changes_nothing(client: TestClient) -> None:
    pid = client.post(
        f"{API}/permissions",
        json={"resource": "invoices", "action": "read", "description": "keep"},
    ).json()["id"]
    body = client.patch(f"{API}/permissions/{pid}", json={}).json()
    assert (body["assignable"], body["description"]) == (False, "keep")


def test_patch_unknown_permission_404(client: TestClient) -> None:
    pid = str(PydanticObjectId())
    response = client.patch(f"{API}/permissions/{pid}", json={"assignable": True})
    assert response.status_code == 404
    assert response.json()["details"] == {"permission_id": pid}


def test_patch_permission_bumps_snapshot_version(client: TestClient) -> None:
    pid = client.post(
        f"{API}/permissions", json={"resource": "invoices", "action": "read"}
    ).json()["id"]
    before = client.get(f"{API}/snapshot").json()["version"]
    client.patch(f"{API}/permissions/{pid}", json={"assignable": True})
    assert client.get(f"{API}/snapshot").json()["version"] > before
