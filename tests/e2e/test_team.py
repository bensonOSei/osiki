"""The tenant team API, end to end over the mock repositories."""

import time
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from osiki.api.routes import team_router
from osiki.decision.decide import decide
from osiki.decision.models import DecisionRequest, Snapshot, UserBundle
from tests.e2e.conftest import API, _role_repos

T1 = f"{API}/tenants/t1/team"
OWNER = {"X-Osiki-Actor": "tenant_user:u-owner"}
DEV = {"X-Osiki-Actor": "developer:dev"}
OTHER_OWNER = {"X-Osiki-Actor": "tenant_user:u-other"}


class World:
    """Tenants t1 and t2, each owned by one user, plus assignable permissions."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        boot = client.put(f"{API}/environment/bootstrap").json()
        self.owner_role: str = boot["owner_role_id"]
        for tenant in ("t1", "t2"):
            assert client.put(
                f"{API}/tenants/{tenant}", json={"name": tenant}
            ).is_success
        self.sales_create = self.permission("sales", "create")
        self.sales_read = self.permission("sales", "read")
        self.refunds_create = self.permission("refunds", "create")
        self.owner_user = self.user("u-owner")
        self.make_owner(self.owner_user, "t1")
        self.make_owner(self.user("u-other"), "t2")
        # The owner may hand on only what they hold: management and sales.
        shop = self.client.post(
            f"{API}/roles",
            json={
                "name": "Shopkeeper",
                "permission_ids": [self.sales_create, self.sales_read],
            },
        ).json()["id"]
        self.assign(self.owner_user, shop, "t1")

    def user(self, external_id: str) -> str:
        r = self.client.put(f"{API}/users/by-external/{external_id}", json={})
        assert r.is_success, r.text
        return str(r.json()["id"])

    def make_owner(self, user_id: str, tenant: str) -> None:
        external = self.client.get(f"{API}/users/{user_id}").json()["external_id"]
        assert self.client.put(f"{API}/tenants/{tenant}/members/{external}").is_success
        self.assign(user_id, self.owner_role, tenant)

    def assign(self, user_id: str, role_id: str, tenant: str) -> None:
        r = self.client.post(
            f"{API}/users/{user_id}/roles",
            json={
                "role_id": role_id,
                "scope": {"tenant_id": tenant},
                "assigned_by": "dev",
            },
        )
        assert r.status_code == 201, r.text

    def permission(self, resource: str, action: str, *, assignable: bool = True) -> str:
        r = self.client.post(
            f"{API}/permissions", json={"resource": resource, "action": action}
        )
        pid = str(r.json()["id"])
        if assignable:
            self.client.patch(f"{API}/permissions/{pid}", json={"assignable": True})
        return pid

    def role(self, name: str, *permission_ids: str, headers: dict[str, str]) -> str:
        r = self.client.post(
            f"{T1}/roles",
            headers=headers,
            json={
                "name": name,
                "grants": [{"permission_id": p} for p in permission_ids],
            },
        )
        assert r.status_code == 201, r.text
        return str(r.json()["id"])

    def allowed(self, user: str, resource: str, action: str) -> bool:
        snapshot = Snapshot.model_validate(self.client.get(f"{API}/snapshot").json())
        bundle = UserBundle.model_validate(
            self.client.get(f"{API}/users/by-external/{user}/bundle").json()
        )
        request = DecisionRequest(
            resource=resource,
            action=action,
            scope={"tenant_id": "t1"},
            now=time.time(),
        )
        return decide(snapshot, bundle, request).allowed


@pytest.fixture
def world(client: TestClient) -> World:
    return World(client)


def test_owner_flow_gives_a_weekend_cashier_sales_but_not_refunds(
    client: TestClient, world: World
) -> None:
    role = world.role(
        "Weekend cashier", world.sales_create, world.sales_read, headers=OWNER
    )
    added = client.post(
        f"{T1}/members",
        headers=OWNER,
        json={"user_id": "u-staff", "name": "Stan", "email": "s@x.io", "role_id": role},
    )
    assert added.status_code == 201, added.text
    assert added.json() == {
        "user_id": "u-staff",
        "name": "Stan",
        "email": "s@x.io",
        "roles": [{"id": role, "name": "Weekend cashier", "kind": "tenant"}],
    }
    assert world.allowed("u-staff", "sales", "create") is True
    assert world.allowed("u-staff", "refunds", "create") is False

    roles = client.get(f"{T1}/roles", headers=OWNER).json()
    by_name = {r["name"]: r for r in roles}
    assert by_name["Weekend cashier"]["holders"] == 1
    assert by_name["Weekend cashier"]["grants"] == [
        {"permission": "sales:create", "condition": None},
        {"permission": "sales:read", "condition": None},
    ]
    assert by_name["Owner"]["kind"] == "template"

    effective = client.get(f"{T1}/members/u-staff/effective", headers=OWNER).json()
    assert {(e["permission"], e["role_name"], e["via"]) for e in effective} == {
        ("sales:create", "Weekend cashier", "direct"),
        ("sales:read", "Weekend cashier", "direct"),
    }


def test_role_update_assign_revoke_and_delete(client: TestClient, world: World) -> None:
    role = world.role("Cashier", world.sales_read, headers=OWNER)
    client.post(
        f"{T1}/members",
        headers=OWNER,
        json={"user_id": "u-staff", "role_id": role},
    )
    patched = client.patch(
        f"{T1}/roles/{role}",
        headers=OWNER,
        json={"name": "Till", "grants": [{"permission_id": world.sales_create}]},
    )
    assert patched.status_code == 200
    assert (patched.json()["name"], patched.json()["grants"]) == (
        "Till",
        [{"permission": "sales:create", "condition": None}],
    )
    # Deleting a role someone holds is refused with role_in_use.
    busy = client.delete(f"{T1}/roles/{role}", headers=OWNER)
    assert busy.status_code == 409
    assert busy.json()["details"] == {"reason": "role_in_use", "role_id": role}

    second = world.role("Stock", world.sales_read, headers=OWNER)
    assigned = client.put(f"{T1}/members/u-staff/roles/{second}", headers=OWNER)
    assert assigned.status_code == 200
    assert {r["name"] for r in assigned.json()["roles"]} == {"Till", "Stock"}
    assert (
        client.delete(f"{T1}/members/u-staff/roles/{role}", headers=OWNER).status_code
        == 204
    )
    assert client.delete(f"{T1}/roles/{role}", headers=OWNER).status_code == 204
    names = {r["name"] for r in client.get(f"{T1}/roles", headers=OWNER).json()}
    assert "Till" not in names
    assert client.delete(f"{T1}/members/u-staff", headers=OWNER).status_code == 204
    gone = client.get(f"{T1}/members/u-staff/effective", headers=OWNER)
    assert gone.status_code == 404


def test_members_are_paginated_with_a_total(client: TestClient, world: World) -> None:
    role = world.role("Cashier", world.sales_read, headers=OWNER)
    for i in range(3):
        client.post(
            f"{T1}/members", headers=OWNER, json={"user_id": f"s{i}", "role_id": role}
        )
    body = client.get(f"{T1}/members", headers=OWNER, params={"page_size": 2}).json()
    assert (body["total"], body["total_pages"], len(body["items"])) == (4, 2, 2)
    last = client.get(
        f"{T1}/members", headers=OWNER, params={"page": 2, "page_size": 2}
    ).json()
    assert len(last["items"]) == 2
    seen = {m["user_id"] for m in body["items"] + last["items"]}
    assert seen == {"u-owner", "s0", "s1", "s2"}


def test_manager_escalation_is_409_with_uncovered(
    client: TestClient, world: World
) -> None:
    # The owner holds management and sales, so refunds:create is not theirs to give.
    r = client.post(
        f"{T1}/roles",
        headers=OWNER,
        json={"name": "Boss", "grants": [{"permission_id": world.refunds_create}]},
    )
    assert r.status_code == 409
    body = r.json()
    assert body["error"] == "conflict"
    assert body["details"] == {"reason": "escalation", "uncovered": "refunds:create"}
    # A developer is exempt from the rule.
    assert world.role("Boss", world.refunds_create, headers=DEV)


def test_last_manager_is_409(client: TestClient, world: World) -> None:
    r = client.delete(f"{T1}/members/u-owner", headers=OWNER)
    assert r.status_code == 409
    assert r.json()["details"] == {"reason": "last_manager"}
    r = client.delete(f"{T1}/members/u-owner/roles/{world.owner_role}", headers=OWNER)
    assert r.status_code == 409
    assert r.json()["details"] == {"reason": "last_manager"}


def test_not_assignable_and_not_offered_are_409_with_reasons(
    client: TestClient, world: World
) -> None:
    hidden = world.permission("hidden", "read", assignable=False)
    r = client.post(
        f"{T1}/roles",
        headers=DEV,
        json={"name": "X", "grants": [{"permission_id": hidden}]},
    )
    assert r.status_code == 409
    assert r.json()["details"] == {
        "reason": "not_assignable",
        "permissions": "hidden:read",
    }
    not_template = client.post(f"{API}/roles", json={"name": "Plain"}).json()["id"]
    r = client.post(
        f"{T1}/roles",
        headers=DEV,
        json={"name": "Y", "grants": [], "copied_from": not_template},
    )
    assert r.status_code == 409
    assert r.json()["details"] == {"reason": "not_offered", "role_id": not_template}


def test_constraint_is_409_with_reason_and_constraint_name(
    client: TestClient, world: World
) -> None:
    def template(name: str, permission_id: str) -> str:
        r = client.post(
            f"{API}/roles",
            json={"name": name, "is_template": True, "permission_ids": [permission_id]},
        )
        return str(r.json()["id"])

    a = template("Till", world.sales_read)
    b = template("Stock", world.sales_create)
    client.post(
        f"{API}/constraints",
        json={
            "name": "no-both",
            "type": "mutual_exclusion",
            "config": {"role_ids": [a, b]},
        },
    )
    added = client.post(
        f"{T1}/members", headers=DEV, json={"user_id": "u-staff", "role_id": a}
    )
    assert added.status_code == 201, added.text
    r = client.put(f"{T1}/members/u-staff/roles/{b}", headers=DEV)
    assert r.status_code == 409
    details = r.json()["details"]
    assert details["reason"] == "constraint"
    assert details["constraint"] == "no-both"
    # The dry run reports it as a violation instead.
    dry = client.post(
        f"{T1}/validate",
        headers=DEV,
        json={"op": "assign_role", "args": {"user_id": "u-staff", "role_id": b}},
    )
    assert [v["kind"] for v in dry.json()["violations"]] == ["constraint"]


def test_validate_reports_violation_and_writes_nothing(
    client: TestClient, world: World
) -> None:
    before = client.get(f"{T1}/audit-logs", headers=OWNER).json()["total"]
    roles_before = client.get(f"{T1}/roles", headers=OWNER).json()
    r = client.post(
        f"{T1}/validate",
        headers=OWNER,
        json={
            "op": "create_role",
            "args": {
                "name": "Boss",
                "grants": [{"permission_id": world.refunds_create}],
            },
        },
    )
    assert r.status_code == 200
    assert r.json() == {
        "violations": [
            {
                "kind": "escalation",
                "message": "Cannot grant permissions you do not hold",
                "details": {"reason": "escalation", "uncovered": "refunds:create"},
            }
        ]
    }
    assert client.get(f"{T1}/roles", headers=OWNER).json() == roles_before
    assert client.get(f"{T1}/audit-logs", headers=OWNER).json()["total"] == before


def test_validate_with_no_violation_is_empty_and_covers_every_op(
    client: TestClient, world: World
) -> None:
    role = world.role("Cashier", world.sales_read, headers=DEV)
    client.post(f"{T1}/members", headers=DEV, json={"user_id": "s1", "role_id": role})
    ops: list[dict[str, Any]] = [
        {"op": "create_role", "args": {"name": "N", "grants": []}},
        {"op": "update_role", "args": {"role_id": role, "name": "Renamed"}},
        {"op": "assign_role", "args": {"user_id": "u-owner", "role_id": role}},
        {"op": "add_member", "args": {"user_id": "new", "role_id": role}},
        {"op": "revoke_role", "args": {"user_id": "s1", "role_id": role}},
        {"op": "remove_member", "args": {"user_id": "s1"}},
    ]
    for body in ops:
        r = client.post(f"{T1}/validate", headers=OWNER, json=body)
        assert (r.status_code, r.json()) == (200, {"violations": []}), body
    # Nothing was written by any of them.
    assert client.get(f"{T1}/members/s1/effective", headers=OWNER).status_code == 200


def test_validate_reports_last_manager(client: TestClient, world: World) -> None:
    r = client.post(
        f"{T1}/validate",
        headers=OWNER,
        json={"op": "remove_member", "args": {"user_id": "u-owner"}},
    )
    assert [v["kind"] for v in r.json()["violations"]] == ["last_manager"]


def test_validate_still_raises_not_found_and_not_manager(
    client: TestClient, world: World
) -> None:
    missing = client.post(
        f"{T1}/validate",
        headers=OWNER,
        json={"op": "remove_member", "args": {"user_id": "ghost"}},
    )
    assert missing.status_code == 404
    denied = client.post(
        f"{T1}/validate",
        headers=OTHER_OWNER,
        json={"op": "remove_member", "args": {"user_id": "u-owner"}},
    )
    assert denied.status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {"op": "nope", "args": {}},
        {"op": "remove_member", "args": {}},
        {"op": "remove_member", "args": {"user_id": "x", "extra": 1}},
        {"op": "create_role", "args": {"name": "", "grants": []}},
    ],
)
def test_validate_rejects_malformed_input(
    client: TestClient, world: World, body: dict[str, Any]
) -> None:
    assert client.post(f"{T1}/validate", headers=OWNER, json=body).status_code == 422


def test_role_name_is_limited_on_input_only(client: TestClient, world: World) -> None:
    long_name = "x" * 121
    r = client.post(f"{T1}/roles", headers=DEV, json={"name": long_name, "grants": []})
    assert r.status_code == 422
    # A stored name longer than any input (as a deleted role's is) still renders.
    role = world.role("Short", world.sales_read, headers=DEV)
    stored = _role_repos["default"]._data[role]
    stored.name = "x" * 200
    listed = client.get(f"{T1}/roles", headers=DEV)
    assert listed.status_code == 200
    assert "x" * 200 in {r["name"] for r in listed.json()}


def test_permissions_lists_assignable_non_builtin(
    client: TestClient, world: World
) -> None:
    world.permission("hidden", "read", assignable=False)
    r = client.get(f"{T1}/permissions", headers=OWNER)
    assert r.status_code == 200
    assert sorted(p["permission_string"] for p in r.json()) == [
        "refunds:create",
        "sales:create",
        "sales:read",
    ]
    assert all(p["assignable"] for p in r.json())


def test_tenant_audit_lists_only_this_tenant(client: TestClient, world: World) -> None:
    client.post(
        f"{API}/audit-logs",
        json={"action": "x", "target_type": "x", "target_id": "x", "tenant_id": "t2"},
    )
    world.role("Cashier", world.sales_read, headers=OWNER)
    body = client.get(f"{T1}/audit-logs", headers=OWNER).json()
    assert body["total"] == 1
    assert [(i["action"], i["tenant_id"], i["actor_id"]) for i in body["items"]] == [
        ("role.create", "t1", "u-owner")
    ]
    paged = client.get(
        f"{T1}/audit-logs", headers=OWNER, params={"page": 2, "page_size": 1}
    ).json()
    assert (paged["items"], paged["total_pages"]) == ([], 1)


def test_malformed_actor_header_is_422(client: TestClient, world: World) -> None:
    r = client.get(f"{T1}/roles", headers={"X-Osiki-Actor": "admin:x"})
    assert r.status_code == 422
    assert r.json()["error"] == "validation_error"


def test_missing_tenant_is_404_for_a_developer(
    client: TestClient, world: World
) -> None:
    r = client.get(f"{API}/tenants/nope/team/roles", headers=DEV)
    assert r.status_code == 404
    assert r.json()["details"] == {"tenant_id": "nope"}
    # No header at all is the anonymous developer.
    assert client.get(f"{API}/tenants/nope/team/roles").status_code == 404


def test_missing_tenant_is_403_for_a_tenant_user(
    client: TestClient, world: World
) -> None:
    for headers in (OWNER, {"X-Osiki-Actor": "tenant_user:ghost"}):
        r = client.get(f"{API}/tenants/nope/team/roles", headers=headers)
        assert r.status_code == 403
        assert r.json()["details"] == {"reason": "not_manager"}


# Every route of the team router, with a request that would succeed for a manager.
def _calls(world: World) -> dict[tuple[str, str], dict[str, Any]]:
    role = world.owner_role
    return {
        ("GET", "/roles"): {},
        ("POST", "/roles"): {"json": {"name": "N", "grants": []}},
        ("PATCH", f"/roles/{role}"): {"json": {"name": "M"}},
        ("DELETE", f"/roles/{role}"): {},
        ("GET", "/members"): {},
        ("POST", "/members"): {"json": {"user_id": "z", "role_id": role}},
        ("PUT", f"/members/u-owner/roles/{role}"): {},
        ("DELETE", f"/members/u-owner/roles/{role}"): {},
        ("DELETE", "/members/u-owner"): {},
        ("GET", "/members/u-owner/effective"): {},
        ("POST", "/validate"): {
            "json": {"op": "remove_member", "args": {"user_id": "u-owner"}}
        },
        ("GET", "/permissions"): {},
        ("GET", "/audit-logs"): {},
    }


def _template(route: APIRoute) -> str:
    path = route.path.removeprefix("/tenants/{tenant_id}/team")
    for param in ("role_id", "user_id"):
        path = path.replace("{" + param + "}", "@" + param)
    return path


def test_the_route_table_covers_every_team_route(world: World) -> None:
    routes = {
        (method, _template(r))
        for r in team_router.routes
        if isinstance(r, APIRoute)
        for method in r.methods
    }
    tested = {
        (
            method,
            path.replace(world.owner_role, "@role_id").replace("u-owner", "@user_id"),
        )
        for method, path in _calls(world)
    }

    # Normalise both sides: a role/user placeholder is one token whichever it is.
    def norm(pair: tuple[str, str]) -> tuple[str, str]:
        return pair[0], pair[1].replace("@role_id", "@x").replace("@user_id", "@x")

    assert {norm(p) for p in tested} == {norm(p) for p in routes}
    assert len(routes) == 13


def test_tenant_user_of_other_tenant_gets_403_on_every_route(
    client: TestClient, world: World
) -> None:
    # u-other owns t2, not t1.
    for (method, path), kwargs in _calls(world).items():
        r = client.request(method, T1 + path, headers=OTHER_OWNER, **kwargs)
        assert r.status_code == 403, (method, path, r.text)
        assert r.json()["details"] == {"reason": "not_manager"}, (method, path)
    # Nothing leaked or changed.
    assert client.get(f"{T1}/members", headers=OWNER).json()["total"] == 1
    # And on a tenant that does not exist, the same 403 (never 404).
    for (method, path), kwargs in _calls(world).items():
        r = client.request(
            method, f"{API}/tenants/nope/team{path}", headers=OTHER_OWNER, **kwargs
        )
        assert r.status_code == 403, (method, path)


def test_developer_gets_404_on_every_route_of_a_missing_tenant(
    client: TestClient, world: World
) -> None:
    for (method, path), kwargs in _calls(world).items():
        r = client.request(method, f"{API}/tenants/nope/team{path}", **kwargs)
        assert r.status_code == 404, (method, path, r.text)


def test_list_tenants_developer_only_with_search(
    client: TestClient, world: World
) -> None:
    client.put(f"{API}/tenants/acme-9", json={"name": "Bakery"})
    client.put(f"{API}/tenants/zz", json={"name": "ACME Foods"})
    r = client.get(f"{API}/tenants", headers=DEV)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    counts = {t["external_id"]: t["member_count"] for t in body["items"]}
    assert counts == {"t1": 1, "t2": 1, "acme-9": 0, "zz": 0}
    found = client.get(f"{API}/tenants", params={"q": "AcMe"}).json()
    assert sorted(t["external_id"] for t in found["items"]) == ["acme-9", "zz"]
    assert found["total"] == 2
    page = client.get(f"{API}/tenants", params={"page": 2, "page_size": 3}).json()
    assert [t["external_id"] for t in page["items"]] == ["zz"]
    # A tenant user, even an owner, is refused.
    denied = client.get(f"{API}/tenants", headers=OWNER)
    assert denied.status_code == 403
    assert denied.json()["details"] == {"reason": "developer_only"}


@pytest.mark.parametrize(
    "path",
    [f"{T1}/members", f"{T1}/audit-logs", f"{API}/tenants"],
)
@pytest.mark.parametrize(
    "params",
    [{"page": 0}, {"page_size": 101}, {"page_size": 0}, {"page": 10**18}],
)
def test_paging_bounds_are_422(
    client: TestClient, world: World, path: str, params: dict[str, int]
) -> None:
    assert client.get(path, headers=DEV, params=params).status_code == 422


def test_tenant_search_query_is_length_limited(
    client: TestClient, world: World
) -> None:
    assert client.get(f"{API}/tenants", params={"q": "x" * 101}).status_code == 422
    assert client.get(f"{API}/tenants", params={"q": "x" * 100}).status_code == 200


def _tenant_role_body(role: str, scope: dict[str, str] | None) -> dict[str, Any]:
    body: dict[str, Any] = {"role_id": role, "assigned_by": "dev"}
    if scope is not None:
        body["scope"] = scope
    return body


@pytest.mark.parametrize("scope", [None, {}, {"tenant_id": "t2"}])
def test_developer_cannot_assign_a_tenant_role_outside_its_tenant(
    client: TestClient, world: World, scope: dict[str, str] | None
) -> None:
    role = world.role("Cashier", world.sales_create, headers=OWNER)
    user = world.user("u-other")  # a member of t2 only
    group = client.post(f"{API}/groups", json={"name": "eng"}).json()["id"]
    body = _tenant_role_body(role, scope)

    for url in (f"{API}/users/{user}/roles", f"{API}/groups/{group}/roles"):
        r = client.post(url, json=body)
        assert r.status_code == 422, r.text
        assert r.json()["error"] == "validation_error"
        assert r.json()["details"] == {"role_id": role, "tenant_id": "t1"}


def test_developer_can_assign_a_tenant_role_in_its_own_tenant(
    client: TestClient, world: World
) -> None:
    role = world.role("Cashier", world.sales_create, headers=OWNER)
    group = client.post(f"{API}/groups", json={"name": "eng"}).json()["id"]

    r = client.post(
        f"{API}/groups/{group}/roles",
        json=_tenant_role_body(role, {"tenant_id": "t1"}),
    )
    assert r.status_code == 201, r.text
    world.assign(world.owner_user, role, "t1")
