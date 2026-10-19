from fastapi.testclient import TestClient

from tests.e2e.conftest import API


def _version(client: TestClient) -> int:
    version: int = client.get(f"{API}/snapshot/version").json()["version"]
    return version


def test_settings_default_to_deny(client: TestClient) -> None:
    assert client.get(f"{API}/settings").json() == {"unmapped": "deny"}


def test_settings_roundtrip(client: TestClient) -> None:
    response = client.put(f"{API}/settings", json={"unmapped": "allow"})

    assert response.status_code == 200
    assert response.json() == {"unmapped": "allow"}
    assert client.get(f"{API}/settings").json() == {"unmapped": "allow"}


def test_settings_reject_unknown_policy(client: TestClient) -> None:
    assert client.put(f"{API}/settings", json={"unmapped": "maybe"}).status_code == 422


def test_settings_write_bumps_config_version(client: TestClient) -> None:
    etag = client.get(f"{API}/snapshot").headers["ETag"]
    before = _version(client)

    client.put(f"{API}/settings", json={"unmapped": "allow"})

    assert _version(client) == before + 1
    fresh = client.get(f"{API}/snapshot", headers={"If-None-Match": etag})
    assert fresh.status_code == 200
    assert fresh.json()["settings"] == {"unmapped": "allow"}


def test_settings_are_per_environment(client: TestClient) -> None:
    client.put(f"{API}/settings", json={"unmapped": "allow"})

    other = client.get(f"{API}/settings", headers={"X-Osiki-Environment": "other"})

    assert other.json() == {"unmapped": "deny"}
