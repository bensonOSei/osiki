from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from tests.e2e.conftest import API

EXPR = {"op": "eq", "left": {"ref": "record.owner_id"}, "right": {"ref": "user.id"}}
ENV_HEADER = "X-Osiki-Environment"


def _perm(client: TestClient, resource: str, action: str, **headers: str) -> str:
    response = client.post(
        f"{API}/permissions",
        json={"resource": resource, "action": action},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _condition(client: TestClient, key: str = "is_owner", **headers: str) -> str:
    response = client.post(
        f"{API}/conditions",
        json={"key": key, "name": key, "expression": EXPR},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


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
    assert data["grants"] == []


def test_create_role_with_permissions(client: TestClient) -> None:
    pid1 = _perm(client, "docs", "read")
    pid2 = _perm(client, "docs", "write")

    response = client.post(
        f"{API}/roles",
        json={"name": "editor", "permission_ids": [pid1, pid2]},
    )
    assert response.status_code == 201
    assert {
        (g["permission_id"], g["condition_id"]) for g in response.json()["grants"]
    } == {
        (pid1, None),
        (pid2, None),
    }


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
    new_pid = _perm(client, "docs", "read")

    response = client.patch(
        f"{API}/roles/{role_id}", json={"permission_ids": [new_pid]}
    )
    assert response.status_code == 200
    assert response.json()["grants"] == [
        {"permission_id": new_pid, "condition_id": None}
    ]


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


# --- Grants ---


def test_create_role_with_conditional_grant(client: TestClient) -> None:
    pid = _perm(client, "invoices", "read")
    cid = _condition(client)

    response = client.post(
        f"{API}/roles",
        json={"name": "own", "grants": [{"permission_id": pid, "condition_id": cid}]},
    )

    assert response.status_code == 201
    assert response.json()["grants"] == [{"permission_id": pid, "condition_id": cid}]


def test_permission_ids_shorthand_becomes_unconditional_grants(
    client: TestClient,
) -> None:
    pid = _perm(client, "invoices", "read")

    response = client.post(f"{API}/roles", json={"name": "r", "permission_ids": [pid]})

    assert response.status_code == 201
    body = response.json()
    assert body["grants"] == [{"permission_id": pid, "condition_id": None}]
    assert "permission_ids" not in body


def test_grants_and_shorthand_merge_and_dedupe(client: TestClient) -> None:
    pid = _perm(client, "invoices", "read")
    cid = _condition(client)

    response = client.post(
        f"{API}/roles",
        json={
            "name": "r",
            "permission_ids": [pid, pid],
            "grants": [
                {"permission_id": pid},
                {"permission_id": pid, "condition_id": cid},
                {"permission_id": pid, "condition_id": cid},
            ],
        },
    )

    assert response.status_code == 201
    assert response.json()["grants"] == [
        {"permission_id": pid, "condition_id": None},
        {"permission_id": pid, "condition_id": cid},
    ]


def test_unknown_condition_422(client: TestClient) -> None:
    pid = _perm(client, "invoices", "read")
    missing = str(PydanticObjectId())

    response = client.post(
        f"{API}/roles",
        json={"name": "r", "grants": [{"permission_id": pid, "condition_id": missing}]},
    )

    assert response.status_code == 422
    assert missing in response.json()["details"]["condition_id"]


def test_unknown_permission_422(client: TestClient) -> None:
    missing = str(PydanticObjectId())

    response = client.post(
        f"{API}/roles", json={"name": "r", "permission_ids": [missing]}
    )

    assert response.status_code == 422
    assert missing in response.json()["details"]["permission_id"]


def test_permission_from_other_environment_422(client: TestClient) -> None:
    pid = _perm(client, "invoices", "read", **{ENV_HEADER: "a"})

    response = client.post(
        f"{API}/roles",
        json={"name": "r", "permission_ids": [pid]},
        headers={ENV_HEADER: "b"},
    )

    assert response.status_code == 422


def test_parent_role_must_exist_in_same_env(client: TestClient) -> None:
    parent = client.post(
        f"{API}/roles", json={"name": "parent"}, headers={ENV_HEADER: "a"}
    ).json()

    response = client.post(
        f"{API}/roles",
        json={"name": "child", "parent_role_id": parent["id"]},
        headers={ENV_HEADER: "b"},
    )

    assert response.status_code == 422
    assert parent["id"] in response.json()["details"]["parent_role_id"]


def test_update_validates_grants_and_parent(client: TestClient) -> None:
    role_id = client.post(f"{API}/roles", json={"name": "r"}).json()["id"]
    missing = str(PydanticObjectId())

    bad_grant = client.patch(
        f"{API}/roles/{role_id}", json={"grants": [{"permission_id": missing}]}
    )
    bad_parent = client.patch(
        f"{API}/roles/{role_id}", json={"parent_role_id": missing}
    )

    assert bad_grant.status_code == 422
    assert bad_parent.status_code == 422


def test_update_replaces_grants(client: TestClient) -> None:
    pid = _perm(client, "invoices", "read")
    cid = _condition(client)
    role_id = client.post(f"{API}/roles", json={"name": "r"}).json()["id"]

    response = client.patch(
        f"{API}/roles/{role_id}",
        json={"grants": [{"permission_id": pid, "condition_id": cid}]},
    )

    assert response.status_code == 200
    assert response.json()["grants"] == [{"permission_id": pid, "condition_id": cid}]


def test_delete_condition_in_use_409(client: TestClient) -> None:
    pid = _perm(client, "invoices", "read")
    cid = _condition(client)
    client.post(
        f"{API}/roles",
        json={"name": "r", "grants": [{"permission_id": pid, "condition_id": cid}]},
    )

    response = client.delete(f"{API}/conditions/{cid}")

    assert response.status_code == 409
    assert response.json()["message"] == "Condition is in use"


def test_delete_unused_condition_still_works(client: TestClient) -> None:
    cid = _condition(client)

    assert client.delete(f"{API}/conditions/{cid}").status_code == 204


def test_malformed_ids_422(client: TestClient) -> None:
    pid = _perm(client, "invoices", "read")

    bad_permission = client.post(
        f"{API}/roles", json={"name": "a", "permission_ids": ["nope"]}
    )
    bad_condition = client.post(
        f"{API}/roles",
        json={"name": "b", "grants": [{"permission_id": pid, "condition_id": "nope"}]},
    )
    bad_parent = client.post(
        f"{API}/roles", json={"name": "c", "parent_role_id": "nope"}
    )

    assert bad_permission.status_code == 422
    assert bad_condition.status_code == 422
    assert bad_parent.status_code == 422


def test_self_parent_422(client: TestClient) -> None:
    role_id = client.post(f"{API}/roles", json={"name": "r"}).json()["id"]

    response = client.patch(f"{API}/roles/{role_id}", json={"parent_role_id": role_id})

    assert response.status_code == 422
    assert role_id in response.json()["details"]["parent_role_id"]


def test_descendant_as_parent_422_but_valid_reparent_ok(client: TestClient) -> None:
    root = client.post(f"{API}/roles", json={"name": "root"}).json()["id"]
    child = client.post(
        f"{API}/roles", json={"name": "child", "parent_role_id": root}
    ).json()["id"]
    other = client.post(f"{API}/roles", json={"name": "other"}).json()["id"]

    cycle = client.patch(f"{API}/roles/{root}", json={"parent_role_id": child})
    reparent = client.patch(f"{API}/roles/{child}", json={"parent_role_id": other})

    assert cycle.status_code == 422
    assert reparent.status_code == 200
    assert reparent.json()["parent_role_id"] == other


def test_deactivated_condition_422(client: TestClient) -> None:
    pid = _perm(client, "invoices", "read")
    cid = _condition(client)
    assert client.delete(f"{API}/conditions/{cid}").status_code == 204

    response = client.post(
        f"{API}/roles",
        json={"name": "r", "grants": [{"permission_id": pid, "condition_id": cid}]},
    )

    assert response.status_code == 422
