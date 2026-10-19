from fastapi.testclient import TestClient

from osiki.api.environment import ENVIRONMENT_HEADER
from tests.e2e.conftest import API


def _user(client: TestClient, external_id: str, headers: dict[str, str] | None = None):
    return client.put(
        f"{API}/users/by-external/{external_id}", json={}, headers=headers
    )


def test_user_upsert_creates_then_updates(client: TestClient) -> None:
    first = client.put(
        f"{API}/users/by-external/u1",
        json={"name": "Kofi", "attributes": {"team_id": "t1"}},
    )
    assert first.status_code == 200
    assert first.json()["name"] == "Kofi"
    assert first.json()["external_id"] == "u1"

    second = client.put(
        f"{API}/users/by-external/u1", json={"attributes": {"team_id": "t2"}}
    )
    assert second.status_code == 200
    assert second.json()["name"] == "Kofi"
    assert second.json()["attributes"] == {"team_id": "t2"}
    assert second.json()["id"] == first.json()["id"]


def test_tenant_upsert_and_get(client: TestClient) -> None:
    created = client.put(
        f"{API}/tenants/acme", json={"name": "Acme", "attributes": {"tier": "gold"}}
    )
    assert created.status_code == 200
    body = created.json()
    assert body["external_id"] == "acme"
    assert body["name"] == "Acme"
    assert body["attributes"] == {"tier": "gold"}

    updated = client.put(f"{API}/tenants/acme", json={"name": "Acme Inc"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Acme Inc"
    assert updated.json()["created_at"] == body["created_at"]

    fetched = client.get(f"{API}/tenants/acme")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Acme Inc"


def test_get_missing_tenant_404(client: TestClient) -> None:
    assert client.get(f"{API}/tenants/nope").status_code == 404


def test_add_member_requires_existing_user_and_tenant(client: TestClient) -> None:
    assert client.put(f"{API}/tenants/acme/members/u1").status_code == 404
    client.put(f"{API}/tenants/acme", json={"name": "Acme"})
    assert client.put(f"{API}/tenants/acme/members/u1").status_code == 404
    _user(client, "u1")
    client.put(f"{API}/tenants/other", json={"name": "Other"})
    assert client.put(f"{API}/tenants/acme/members/ghost").status_code == 404
    assert client.put(f"{API}/tenants/acme/members/u1").status_code == 204


def test_add_member_idempotent(client: TestClient) -> None:
    client.put(f"{API}/tenants/acme", json={"name": "Acme"})
    _user(client, "u1")
    assert client.put(f"{API}/tenants/acme/members/u1").status_code == 204
    assert client.put(f"{API}/tenants/acme/members/u1").status_code == 204
    listing = client.get(f"{API}/tenants/acme/members")
    assert listing.status_code == 200
    assert listing.json()["items"] == ["u1"]


def test_remove_member(client: TestClient) -> None:
    client.put(f"{API}/tenants/acme", json={"name": "Acme"})
    _user(client, "u1")
    client.put(f"{API}/tenants/acme/members/u1")
    assert client.delete(f"{API}/tenants/acme/members/u1").status_code == 204
    assert client.get(f"{API}/tenants/acme/members").json()["items"] == []


def test_remove_non_member_404(client: TestClient) -> None:
    client.put(f"{API}/tenants/acme", json={"name": "Acme"})
    assert client.delete(f"{API}/tenants/acme/members/u1").status_code == 404


def test_tenant_isolated_by_environment(client: TestClient) -> None:
    a = {ENVIRONMENT_HEADER: "a"}
    b = {ENVIRONMENT_HEADER: "b"}
    client.put(f"{API}/tenants/acme", json={"name": "Acme"}, headers=a)
    assert client.get(f"{API}/tenants/acme", headers=a).status_code == 200
    assert client.get(f"{API}/tenants/acme", headers=b).status_code == 404
