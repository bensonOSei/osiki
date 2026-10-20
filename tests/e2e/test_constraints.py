import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from osiki.api.dependencies import get_role_repository
from tests.e2e.conftest import API, app
from tests.mocks.factories import make_role

MUTUAL_EXCLUSION_DATA = {
    "name": "no-dual-signing",
    "description": "Cannot be both initiator and approver",
    "type": "mutual_exclusion",
    "config": {
        "role_ids": [str(PydanticObjectId()), str(PydanticObjectId())],
    },
}

CARDINALITY_DATA = {
    "name": "max-admins",
    "type": "cardinality",
    "config": {
        "role_id": str(PydanticObjectId()),
        "max_assignments": 5,
        "scope_level": "global",
    },
}

PREREQUISITE_DATA = {
    "name": "editor-requires-viewer",
    "type": "prerequisite",
    "config": {
        "role_id": str(PydanticObjectId()),
        "requires_role_id": str(PydanticObjectId()),
    },
}


# --- Create Constraint ---


def test_create_mutual_exclusion(client: TestClient) -> None:
    response = client.post(f"{API}/constraints", json=MUTUAL_EXCLUSION_DATA)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "no-dual-signing"
    assert data["type"] == "mutual_exclusion"
    assert data["is_active"] is True
    assert len(data["config"]["role_ids"]) == 2


def test_create_cardinality(client: TestClient) -> None:
    response = client.post(f"{API}/constraints", json=CARDINALITY_DATA)
    assert response.status_code == 201
    data = response.json()
    assert data["type"] == "cardinality"
    assert data["config"]["max_assignments"] == 5
    assert data["config"]["scope_level"] == "global"


def test_create_prerequisite(client: TestClient) -> None:
    response = client.post(f"{API}/constraints", json=PREREQUISITE_DATA)
    assert response.status_code == 201
    data = response.json()
    assert data["type"] == "prerequisite"
    assert data["config"]["requires_role_id"] is not None


# --- Get Constraint ---


def test_get_constraint(client: TestClient) -> None:
    create_resp = client.post(f"{API}/constraints", json=MUTUAL_EXCLUSION_DATA)
    constraint_id = create_resp.json()["id"]

    response = client.get(f"{API}/constraints/{constraint_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "no-dual-signing"


def test_get_constraint_not_found(client: TestClient) -> None:
    fake_id = str(PydanticObjectId())
    response = client.get(f"{API}/constraints/{fake_id}")
    assert response.status_code == 404


# --- Update Constraint ---


def test_update_constraint_name(client: TestClient) -> None:
    create_resp = client.post(f"{API}/constraints", json=MUTUAL_EXCLUSION_DATA)
    constraint_id = create_resp.json()["id"]

    response = client.patch(
        f"{API}/constraints/{constraint_id}", json={"name": "renamed"}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "renamed"


def test_update_constraint_description(client: TestClient) -> None:
    create_resp = client.post(f"{API}/constraints", json=MUTUAL_EXCLUSION_DATA)
    constraint_id = create_resp.json()["id"]

    response = client.patch(
        f"{API}/constraints/{constraint_id}",
        json={"description": "updated description"},
    )
    assert response.status_code == 200
    assert response.json()["description"] == "updated description"


def test_update_constraint_config(client: TestClient) -> None:
    create_resp = client.post(f"{API}/constraints", json=CARDINALITY_DATA)
    constraint_id = create_resp.json()["id"]

    new_config = {
        "role_id": CARDINALITY_DATA["config"]["role_id"],
        "max_assignments": 10,
        "scope_level": "per_tenant",
    }
    response = client.patch(
        f"{API}/constraints/{constraint_id}", json={"config": new_config}
    )
    assert response.status_code == 200
    assert response.json()["config"]["max_assignments"] == 10
    assert response.json()["config"]["scope_level"] == "per_tenant"


def test_update_constraint_not_found(client: TestClient) -> None:
    fake_id = str(PydanticObjectId())
    response = client.patch(f"{API}/constraints/{fake_id}", json={"name": "x"})
    assert response.status_code == 404


# --- Delete Constraint ---


def test_delete_constraint(client: TestClient) -> None:
    create_resp = client.post(f"{API}/constraints", json=MUTUAL_EXCLUSION_DATA)
    constraint_id = create_resp.json()["id"]

    response = client.delete(f"{API}/constraints/{constraint_id}")
    assert response.status_code == 204


def test_delete_constraint_not_found(client: TestClient) -> None:
    fake_id = str(PydanticObjectId())
    response = client.delete(f"{API}/constraints/{fake_id}")
    assert response.status_code == 404


# --- List Constraints ---


def test_list_constraints_empty(client: TestClient) -> None:
    response = client.get(f"{API}/constraints")
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_list_constraints(client: TestClient) -> None:
    client.post(f"{API}/constraints", json=MUTUAL_EXCLUSION_DATA)
    client.post(f"{API}/constraints", json=CARDINALITY_DATA)

    response = client.get(f"{API}/constraints")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 2


def test_list_constraints_filter_by_type(client: TestClient) -> None:
    client.post(f"{API}/constraints", json=MUTUAL_EXCLUSION_DATA)
    client.post(f"{API}/constraints", json=CARDINALITY_DATA)
    client.post(f"{API}/constraints", json=PREREQUISITE_DATA)

    response = client.get(f"{API}/constraints", params={"type": "mutual_exclusion"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["type"] == "mutual_exclusion"


def test_list_constraints_pagination(client: TestClient) -> None:
    for i in range(3):
        client.post(
            f"{API}/constraints",
            json={
                "name": f"constraint-{i}",
                "type": "mutual_exclusion",
                "config": {"role_ids": [str(PydanticObjectId())]},
            },
        )

    response = client.get(f"{API}/constraints", params={"page": 1, "page_size": 2})
    assert len(response.json()["items"]) == 2

    response = client.get(f"{API}/constraints", params={"page": 2, "page_size": 2})
    assert len(response.json()["items"]) == 1


# --- Constraints target project roles and templates, never tenant roles ---


def _tenant_role() -> str:
    role = make_role(name="Tenant Role", tenant_id="acme")
    app.dependency_overrides[get_role_repository]("default")._store(str(role.id), role)
    return str(role.id)


def _config_with(field: str, role_id: str) -> dict:
    other = str(PydanticObjectId())
    return {
        "role_ids": {"role_ids": [other, role_id]},
        "role_id": {"role_id": role_id, "max_assignments": 1},
        "requires_role_id": {"role_id": other, "requires_role_id": role_id},
    }[field]


@pytest.mark.parametrize(
    ("field", "kind"),
    [
        ("role_ids", "mutual_exclusion"),
        ("role_id", "cardinality"),
        ("requires_role_id", "prerequisite"),
    ],
)
def test_create_rejects_tenant_role(client: TestClient, field: str, kind: str) -> None:
    tenant_role = _tenant_role()

    response = client.post(
        f"{API}/constraints",
        json={"name": "bad", "type": kind, "config": _config_with(field, tenant_role)},
    )

    assert response.status_code == 422
    assert response.json()["details"]["role_id"] == tenant_role
    assert client.get(f"{API}/constraints").json()["items"] == []


def test_create_accepts_project_role_and_template(client: TestClient) -> None:
    project = client.post(f"{API}/roles", json={"name": "plain"}).json()["id"]
    template = make_role(name="Tmpl", is_template=True)
    app.dependency_overrides[get_role_repository]("default")._store(
        str(template.id), template
    )

    response = client.post(
        f"{API}/constraints",
        json={
            "name": "ok",
            "type": "mutual_exclusion",
            "config": {"role_ids": [project, str(template.id)]},
        },
    )

    assert response.status_code == 201


def test_update_rejects_tenant_role(client: TestClient) -> None:
    created = client.post(f"{API}/constraints", json=MUTUAL_EXCLUSION_DATA).json()
    tenant_role = _tenant_role()

    response = client.patch(
        f"{API}/constraints/{created['id']}",
        json={"config": {"role_ids": [str(PydanticObjectId()), tenant_role]}},
    )

    assert response.status_code == 422
    unchanged = client.get(f"{API}/constraints/{created['id']}").json()
    assert (
        unchanged["config"]["role_ids"] == MUTUAL_EXCLUSION_DATA["config"]["role_ids"]
    )
