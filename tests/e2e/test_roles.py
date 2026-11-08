import time

import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

from osiki.api.dependencies import (
    get_group_role_repository,
    get_role_repository,
    get_user_role_repository,
)
from osiki.api.routes.roles import _to_read
from osiki.models.base import Scope
from osiki.models.role import Role
from tests.e2e.conftest import API, app
from tests.mocks import (
    MockGroupRoleRepository,
    MockRoleRepository,
    MockUserRoleRepository,
    make_group_role,
    make_role,
    make_user_role,
)

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


# --- Project roles API vs tenant-owned roles and templates ---


def _role_repo() -> MockRoleRepository:
    repo: MockRoleRepository = app.dependency_overrides[get_role_repository]("default")
    return repo


def _tenant_role(name: str = "Tenant Role", tenant_id: str = "acme") -> str:
    role = make_role(name=name, tenant_id=tenant_id)
    _role_repo()._store(str(role.id), role)
    return str(role.id)


def test_project_roles_api_hides_tenant_roles(client: TestClient) -> None:
    rid = _tenant_role()
    project = client.post(f"{API}/roles", json={"name": "project"}).json()["id"]

    assert client.get(f"{API}/roles/{rid}").status_code == 404
    assert client.patch(f"{API}/roles/{rid}", json={"name": "x"}).status_code == 404
    assert client.delete(f"{API}/roles/{rid}").status_code == 404
    listed = [r["id"] for r in client.get(f"{API}/roles").json()["items"]]
    assert listed == [project]
    # Delete was refused, not just hidden: the role is still active.
    tenant_role = _role_repo()._get(rid)
    assert tenant_role is not None and tenant_role.is_active is True


def test_tenant_role_cannot_be_a_parent(client: TestClient) -> None:
    rid = _tenant_role()
    response = client.post(
        f"{API}/roles", json={"name": "child", "parent_role_id": rid}
    )
    assert response.status_code == 422
    assert response.json()["details"] == {"parent_role_id": rid}


def test_project_and_tenant_role_may_share_a_name(client: TestClient) -> None:
    _tenant_role(name="Support")
    assert client.post(f"{API}/roles", json={"name": "Support"}).status_code == 201
    assert client.post(f"{API}/roles", json={"name": "Support"}).status_code == 409


def test_role_read_exposes_template_fields(client: TestClient) -> None:
    body = client.post(
        f"{API}/roles", json={"name": "starter", "is_template": True}
    ).json()
    assert body["is_template"] is True
    assert body["tenant_id"] is None
    assert body["copied_from"] is None
    plain = client.post(f"{API}/roles", json={"name": "plain"}).json()
    assert plain["is_template"] is False


def test_is_template_is_updatable(client: TestClient) -> None:
    rid = client.post(f"{API}/roles", json={"name": "starter"}).json()["id"]
    on = client.patch(f"{API}/roles/{rid}", json={"is_template": True}).json()
    assert on["is_template"] is True
    kept = client.patch(f"{API}/roles/{rid}", json={"description": "d"}).json()
    assert kept["is_template"] is True
    off = client.patch(f"{API}/roles/{rid}", json={"is_template": False}).json()
    assert off["is_template"] is False


def test_tenant_id_and_copied_from_are_read_only(client: TestClient) -> None:
    created = client.post(
        f"{API}/roles",
        json={"name": "r", "tenant_id": "acme", "copied_from": str(PydanticObjectId())},
    ).json()
    assert created["tenant_id"] is None
    assert created["copied_from"] is None
    patched = client.patch(
        f"{API}/roles/{created['id']}", json={"tenant_id": "acme"}
    ).json()
    assert patched["tenant_id"] is None


def test_tenant_role_copied_from_is_rendered() -> None:
    source = PydanticObjectId()
    read = _to_read(make_role(tenant_id="acme", copied_from=source))
    assert (read.tenant_id, read.copied_from) == ("acme", str(source))


# --- Role name conflicts and list total ---


def test_create_role_reusing_deleted_name_409(client: TestClient) -> None:
    rid = client.post(f"{API}/roles", json={"name": "Auditor"}).json()["id"]
    assert client.delete(f"{API}/roles/{rid}").status_code == 204

    response = client.post(f"{API}/roles", json={"name": "Auditor"})

    assert response.status_code == 409
    assert response.json()["details"] == {"name": "Auditor"}


def test_rename_role_to_taken_name_409(client: TestClient) -> None:
    client.post(f"{API}/roles", json={"name": "A"})
    b = client.post(f"{API}/roles", json={"name": "B"}).json()["id"]

    response = client.patch(f"{API}/roles/{b}", json={"name": "A"})

    assert response.status_code == 409
    assert client.patch(f"{API}/roles/{b}", json={"name": "B"}).status_code == 200


def test_create_role_duplicate_key_race_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(role: Role, **_: object) -> Role:
        raise DuplicateKeyError("E11000 duplicate key")

    monkeypatch.setattr(_role_repo(), "create", boom)

    response = client.post(f"{API}/roles", json={"name": "Racer"})

    assert response.status_code == 409
    assert response.json()["details"] == {"name": "Racer"}


def test_rename_role_duplicate_key_race_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    rid = client.post(f"{API}/roles", json={"name": "Before"}).json()["id"]

    async def boom(role: Role, **_: object) -> Role:
        raise DuplicateKeyError("E11000 duplicate key")

    monkeypatch.setattr(_role_repo(), "update", boom)

    response = client.patch(f"{API}/roles/{rid}", json={"name": "After"})

    assert response.status_code == 409
    assert response.json()["details"] == {"name": "After"}


def test_list_roles_total_counts_all_pages(client: TestClient) -> None:
    for name in ("r1", "r2", "r3"):
        client.post(f"{API}/roles", json={"name": name})

    body = client.get(f"{API}/roles", params={"page_size": 2}).json()

    assert len(body["items"]) == 2
    assert body["total"] == 3


# --- Audit ---

DEV = {"X-Osiki-Actor": "developer:dev-1"}


def _audit(client: TestClient, action: str) -> list[dict[str, object]]:
    items = client.get(f"{API}/audit-logs").json()["items"]
    return [i for i in items if i["action"] == action]


def test_role_writes_are_audited(client: TestClient) -> None:
    perm = _perm(client, "sales", "create")
    created = client.post(
        f"{API}/roles",
        json={"name": "seller", "permission_ids": [perm]},
        headers=DEV,
    )
    role_id = created.json()["id"]
    renamed = client.patch(
        f"{API}/roles/{role_id}",
        json={"name": "closer", "permission_ids": []},
        headers=DEV,
    )
    assert renamed.status_code == 200
    assert client.delete(f"{API}/roles/{role_id}", headers=DEV).status_code == 204

    [create] = _audit(client, "role.create")
    assert create["actor_id"] == "dev-1"
    assert create["actor_type"] == "developer"
    assert create["tenant_id"] is None
    assert create["target_type"] == "role"
    assert create["target_id"] == role_id
    assert create["before"] is None
    assert create["after"] == {
        "name": "seller",
        "is_template": False,
        "grants": ["sales:create"],
    }
    [update] = _audit(client, "role.update")
    assert update["before"] == create["after"]
    assert update["after"] == {"name": "closer", "is_template": False, "grants": []}
    [delete] = _audit(client, "role.delete")
    assert delete["before"] == update["after"]
    assert delete["after"] is None
    assert delete["actor_id"] == "dev-1"


def test_conditional_grant_audit_string(client: TestClient) -> None:
    perm = _perm(client, "sales", "create")
    cond = _condition(client, "own_branch")
    response = client.post(
        f"{API}/roles",
        json={
            "name": "seller",
            "grants": [{"permission_id": perm, "condition_id": cond}],
        },
        headers=DEV,
    )
    assert response.status_code == 201
    [create] = _audit(client, "role.create")
    assert create["after"]["grants"] == ["sales:create?own_branch"]  # type: ignore[index]


def test_failed_role_writes_are_not_audited(client: TestClient) -> None:
    client.post(f"{API}/roles", json={"name": "seller"})
    dup = client.post(f"{API}/roles", json={"name": "seller"})
    assert dup.status_code == 409
    assert len(_audit(client, "role.create")) == 1


# --- Template usage counts ---


def _usage_repos(
    env: str = "default",
) -> tuple[MockUserRoleRepository, MockGroupRoleRepository, MockRoleRepository]:
    users: MockUserRoleRepository = app.dependency_overrides[get_user_role_repository](
        env
    )
    groups: MockGroupRoleRepository = app.dependency_overrides[
        get_group_role_repository
    ](env)
    roles: MockRoleRepository = app.dependency_overrides[get_role_repository](env)
    return users, groups, roles


def _assign(repo: MockUserRoleRepository, role_id: str, tenant: str | None) -> None:
    ur = make_user_role(
        PydanticObjectId(),
        PydanticObjectId(role_id),
        Scope(tenant_id=tenant),
    )
    repo._store(str(ur.id), ur)


def _usage(client: TestClient, *ids: str, **headers: str) -> list[dict[str, object]]:
    response = client.get(
        f"{API}/roles/usage",
        params=[("role_id", i) for i in ids],
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body: list[dict[str, object]] = response.json()
    return body


def test_role_usage_counts_distinct_tenants(client: TestClient) -> None:
    template = client.post(f"{API}/roles", json={"name": "t", "is_template": True})
    rid = template.json()["id"]
    users, groups, _ = _usage_repos()
    _assign(users, rid, "a")
    _assign(users, rid, "a")
    _assign(users, rid, "b")
    _assign(users, rid, None)
    group_role = make_group_role(
        PydanticObjectId(), PydanticObjectId(rid), Scope(tenant_id="c")
    )
    groups._store(str(group_role.id), group_role)
    # Tenant "a" again through a group: the union counts it once.
    again = make_group_role(
        PydanticObjectId(), PydanticObjectId(rid), Scope(tenant_id="a")
    )
    groups._store(str(again.id), again)
    no_tenant = make_group_role(PydanticObjectId(), PydanticObjectId(rid))
    groups._store(str(no_tenant.id), no_tenant)

    assert _usage(client, rid) == [{"role_id": rid, "tenants": 3, "copies": 0}]


def test_role_usage_ignores_expired_revoked_and_other_environments(
    client: TestClient,
) -> None:
    rid = client.post(f"{API}/roles", json={"name": "t"}).json()["id"]
    users, groups, _ = _usage_repos()
    other_users, _, _ = _usage_repos("elsewhere")
    expired = make_user_role(
        PydanticObjectId(),
        PydanticObjectId(rid),
        Scope(tenant_id="old"),
        expires_at=time.time() - 10,
    )
    users._store(str(expired.id), expired)
    revoked = make_user_role(
        PydanticObjectId(), PydanticObjectId(rid), Scope(tenant_id="gone")
    )
    revoked.is_active = False
    users._store(str(revoked.id), revoked)
    lapsed_group = make_group_role(
        PydanticObjectId(),
        PydanticObjectId(rid),
        Scope(tenant_id="old-group"),
        expires_at=time.time() - 10,
    )
    groups._store(str(lapsed_group.id), lapsed_group)
    future = make_user_role(
        PydanticObjectId(),
        PydanticObjectId(rid),
        Scope(tenant_id="live"),
        expires_at=time.time() + 3600,
    )
    users._store(str(future.id), future)
    _assign(other_users, rid, "elsewhere-tenant")

    assert _usage(client, rid)[0]["tenants"] == 1


def test_role_usage_counts_active_copies(client: TestClient) -> None:
    rid = client.post(f"{API}/roles", json={"name": "t", "is_template": True}).json()[
        "id"
    ]
    _, _, roles = _usage_repos()
    source = PydanticObjectId(rid)
    for name, tenant, active in [
        ("c1", "a", True),
        ("c2", "b", True),
        ("c3", "c", False),
    ]:
        copy = make_role(
            name=name, tenant_id=tenant, copied_from=source, is_active=active
        )
        roles._store(str(copy.id), copy)

    assert _usage(client, rid)[0]["copies"] == 2


def test_role_usage_orders_canonicalizes_and_zeroes_unknown(
    client: TestClient,
) -> None:
    first = client.post(f"{API}/roles", json={"name": "one"}).json()["id"]
    second = client.post(f"{API}/roles", json={"name": "two"}).json()["id"]
    users, _, _ = _usage_repos()
    _assign(users, second, "a")
    tenant_role = _tenant_role()
    _assign(users, tenant_role, "a")
    unknown = str(PydanticObjectId())

    result = _usage(client, second.upper(), "not-an-id", tenant_role, unknown, first)

    assert result == [
        {"role_id": second, "tenants": 1, "copies": 0},
        {"role_id": "not-an-id", "tenants": 0, "copies": 0},
        {"role_id": tenant_role, "tenants": 0, "copies": 0},
        {"role_id": unknown, "tenants": 0, "copies": 0},
        {"role_id": first, "tenants": 0, "copies": 0},
    ]


def test_role_usage_limits_ids(client: TestClient) -> None:
    ids = [str(PydanticObjectId()) for _ in range(101)]
    response = client.get(f"{API}/roles/usage", params=[("role_id", i) for i in ids])
    assert response.status_code == 422
    assert client.get(f"{API}/roles/usage").status_code == 422
    assert len(_usage(client, *ids[:100])) == 100


def test_role_usage_with_no_known_role_is_all_zeros(client: TestClient) -> None:
    unknown = str(PydanticObjectId())

    assert _usage(client, "not-an-id") == [
        {"role_id": "not-an-id", "tenants": 0, "copies": 0}
    ]
    assert _usage(client, unknown) == [{"role_id": unknown, "tenants": 0, "copies": 0}]
