from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.e2e.conftest import API

ENV_HEADER = "X-Osiki-Environment"

DELETE_INVOICE = {
    "method": "DELETE",
    "path": "/invoices/{id}",
    "permission": "invoices:delete",
    "record_type": "invoice",
    "record_id_param": "id",
}


def _version(client: TestClient) -> int:
    version: int = client.get(f"{API}/snapshot/version").json()["version"]
    return version


def test_snapshot_includes_mappings_and_settings(client: TestClient) -> None:
    assert (
        client.put(f"{API}/endpoints/mapping", json=DELETE_INVOICE).status_code == 200
    )
    client.put(f"{API}/settings", json={"unmapped": "allow"})

    snapshot = client.get(f"{API}/snapshot").json()

    assert snapshot["endpoints"][0] == {
        **DELETE_INVOICE,
        "public": False,
        "on_unavailable": None,
    }
    assert snapshot["settings"] == {"unmapped": "allow"}


def test_snapshot_renders_mappings_sorted_by_path_then_method(
    client: TestClient,
) -> None:
    for method, path in [("POST", "/b"), ("PUT", "/a"), ("GET", "/b")]:
        client.put(
            f"{API}/endpoints/mapping",
            json={"method": method, "path": path, "permission": "x:y"},
        )

    endpoints = client.get(f"{API}/snapshot").json()["endpoints"]

    assert [(e["path"], e["method"]) for e in endpoints] == [
        ("/a", "PUT"),
        ("/b", "GET"),
        ("/b", "POST"),
    ]


def test_mapping_write_bumps_config_version(client: TestClient) -> None:
    first = client.get(f"{API}/snapshot")
    etag = first.headers["ETag"]
    before = _version(client)

    client.put(f"{API}/endpoints/mapping", json=DELETE_INVOICE)
    after_put = _version(client)
    stale = client.get(f"{API}/snapshot", headers={"If-None-Match": etag})
    assert stale.status_code == 200
    assert stale.json()["endpoints"][0]["path"] == "/invoices/{id}"

    changed = {**DELETE_INVOICE, "permission": "invoices:purge"}
    client.put(f"{API}/endpoints/mapping", json=changed)
    after_update = _version(client)
    assert client.get(f"{API}/snapshot").json()["endpoints"][0]["permission"] == (
        "invoices:purge"
    )

    client.delete(
        f"{API}/endpoints/mapping",
        params={"method": "DELETE", "path": "/invoices/{id}"},
    )
    after_delete = _version(client)
    assert client.get(f"{API}/snapshot").json()["endpoints"] == []

    assert before < after_put < after_update < after_delete


def test_discovery_does_not_bump_config_version(client: TestClient) -> None:
    before = _version(client)

    client.post(
        f"{API}/endpoints/discovered",
        json={"endpoints": [{"method": "GET", "path": "/x"}]},
    )

    assert _version(client) == before


def test_discovered_then_listed_as_unmapped(client: TestClient) -> None:
    response = client.post(
        f"{API}/endpoints/discovered",
        json={
            "endpoints": [
                {"method": "POST", "path": "/b"},
                {"method": "GET", "path": "/b"},
                {"method": "GET", "path": "/b"},
                {"method": "GET", "path": "/a"},
            ]
        },
    )
    assert response.status_code == 202
    assert response.json() == {"recorded": 3}

    rows = client.get(f"{API}/endpoints").json()

    assert [(r["path"], r["method"]) for r in rows] == [
        ("/a", "GET"),
        ("/b", "GET"),
        ("/b", "POST"),
    ]
    assert all(r["mapping"] is None and r["last_seen"] is not None for r in rows)


def test_listing_unions_discovered_and_mapped(client: TestClient) -> None:
    client.post(
        f"{API}/endpoints/discovered",
        json={"endpoints": [{"method": "DELETE", "path": "/invoices/{id}"}]},
    )
    client.put(f"{API}/endpoints/mapping", json=DELETE_INVOICE)
    client.put(
        f"{API}/endpoints/mapping",
        json={"method": "GET", "path": "/health", "public": True},
    )

    rows = {(r["method"], r["path"]): r for r in client.get(f"{API}/endpoints").json()}

    mapped_and_seen = rows[("DELETE", "/invoices/{id}")]
    assert mapped_and_seen["mapping"]["permission"] == "invoices:delete"
    assert mapped_and_seen["last_seen"] is not None
    mapped_only = rows[("GET", "/health")]
    assert mapped_only["mapping"]["public"] is True
    assert mapped_only["last_seen"] is None


def test_rediscovery_keeps_one_row(client: TestClient) -> None:
    body = {"endpoints": [{"method": "GET", "path": "/x"}]}
    client.post(f"{API}/endpoints/discovered", json=body)
    client.post(f"{API}/endpoints/discovered", json=body)

    assert len(client.get(f"{API}/endpoints").json()) == 1


@pytest.mark.parametrize("count", [0, 1001])
def test_discovered_batch_size_limits(client: TestClient, count: int) -> None:
    endpoints = [{"method": "GET", "path": f"/p{i}"} for i in range(count)]

    response = client.post(f"{API}/endpoints/discovered", json={"endpoints": endpoints})

    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"method": "GET", "path": "/x"},
        {"method": "GET", "path": "/x", "public": False, "permission": None},
        {**DELETE_INVOICE, "record_id_param": "other"},
        {**DELETE_INVOICE, "record_id_param": "i"},
        {**DELETE_INVOICE, "method": "TRACE"},
        {**DELETE_INVOICE, "permission": "a:b:c"},
        {**DELETE_INVOICE, "permission": "nocolon"},
        {**DELETE_INVOICE, "path": "invoices/{id}"},
        {**DELETE_INVOICE, "record_type": "Bad-Slug"},
        {"method": "GET", "path": "/x", "permission": "a:b", "record_type": "invoice"},
        {"method": "GET", "path": "/x", "permission": "a:b", "record_id_param": "id"},
    ],
)
def test_mapping_validation_422(client: TestClient, body: dict[str, Any]) -> None:
    response = client.put(f"{API}/endpoints/mapping", json=body)

    assert response.status_code == 422
    assert client.get(f"{API}/snapshot").json()["endpoints"] == []


def test_record_id_param_with_converter_accepted(client: TestClient) -> None:
    body = {**DELETE_INVOICE, "path": "/invoices/{id:int}"}

    response = client.put(f"{API}/endpoints/mapping", json=body)

    assert response.status_code == 200
    assert response.json()["path"] == "/invoices/{id:int}"


def test_public_mapping_needs_no_permission(client: TestClient) -> None:
    response = client.put(
        f"{API}/endpoints/mapping",
        json={"method": "GET", "path": "/health", "public": True},
    )

    assert response.status_code == 200
    assert response.json()["permission"] is None


def test_delete_mapping_404(client: TestClient) -> None:
    before = _version(client)

    response = client.delete(
        f"{API}/endpoints/mapping", params={"method": "GET", "path": "/nope"}
    )

    assert response.status_code == 404
    assert _version(client) == before


def test_delete_mapping_204(client: TestClient) -> None:
    client.put(f"{API}/endpoints/mapping", json=DELETE_INVOICE)

    response = client.delete(
        f"{API}/endpoints/mapping",
        params={"method": "DELETE", "path": "/invoices/{id}"},
    )

    assert response.status_code == 204


def test_endpoints_env_isolated(client: TestClient) -> None:
    other = {ENV_HEADER: "other"}
    client.put(f"{API}/endpoints/mapping", json=DELETE_INVOICE)
    client.post(
        f"{API}/endpoints/discovered",
        json={"endpoints": [{"method": "GET", "path": "/x"}]},
    )

    assert client.get(f"{API}/endpoints", headers=other).json() == []
    assert client.get(f"{API}/snapshot", headers=other).json()["endpoints"] == []
    assert len(client.get(f"{API}/snapshot").json()["endpoints"]) == 1
