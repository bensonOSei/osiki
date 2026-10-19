import random
from typing import Any

import pytest
from fastapi.testclient import TestClient

from osiki.configs.settings import get_settings
from tests.e2e.conftest import API, _access_log_repos
from tests.mocks.repositories import MockAccessLogRepository


def _check(
    client: TestClient, environment: str | None = None, **overrides: Any
) -> None:
    body: dict[str, Any] = {
        "user_id": "ghost",
        "resource": "documents",
        "action": "read",
        "scope": {"tenant_id": "acme"},
    }
    body.update(overrides)
    headers = {"X-Osiki-Environment": environment} if environment else {}
    response = client.post(f"{API}/authorization/check", json=body, headers=headers)
    assert response.status_code == 200


def _logs(environment: str = "default") -> list[Any]:
    repo = _access_log_repos.get(environment)
    return repo._scoped() if repo else []


def _entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "timestamp": 1_700_000_000.5,
        "user_id": "u-1",
        "resource": "documents",
        "action": "read",
        "scope": {"tenant_id": "acme"},
        "allowed": True,
        "matched_permission": "documents:read",
        "condition": "own_team",
        "latency_ms": 0.2,
    }
    entry.update(overrides)
    return entry


@pytest.fixture(autouse=True)
def _rate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "access_log_success_sample_rate", 0.1)


def test_denial_always_logged(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(random, "random", lambda: 0.99)
    _check(client)
    logs = _logs()
    assert len(logs) == 1
    assert logs[0].allowed is False
    assert logs[0].denial_reason == "unknown_user"
    assert logs[0].tenant_id == "acme"
    assert logs[0].source == "server"
    assert logs[0].latency_ms >= 0


def test_success_sampled(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    client.put(f"{API}/users/by-external/u1", json={})
    perm = client.post(
        f"{API}/permissions", json={"resource": "documents", "action": "read"}
    ).json()
    role = client.post(
        f"{API}/roles", json={"name": "r", "permission_ids": [perm["id"]]}
    ).json()
    user = client.put(f"{API}/users/by-external/u1", json={}).json()
    client.post(
        f"{API}/users/{user['id']}/roles",
        json={"role_id": role["id"], "assigned_by": "admin"},
    )

    monkeypatch.setattr(random, "random", lambda: 0.5)
    _check(client, user_id="u1", scope=None)
    assert _logs() == []

    monkeypatch.setattr(random, "random", lambda: 0.05)
    _check(client, user_id="u1", scope=None)
    logs = _logs()
    assert len(logs) == 1
    assert logs[0].allowed is True
    assert logs[0].matched_permission == "documents:read"
    assert logs[0].tenant_id is None


def test_logging_failure_does_not_change_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(self: MockAccessLogRepository, access_log: Any) -> Any:
        raise RuntimeError("db down")

    monkeypatch.setattr(MockAccessLogRepository, "create", boom)
    _check(client)
    assert _logs() == []


def test_batch_ingest_202_and_stored_as_sdk(client: TestClient) -> None:
    response = client.post(
        f"{API}/access-logs/batch",
        json={"entries": [_entry(), _entry(allowed=False, denial_reason="x")]},
    )
    assert response.status_code == 202
    assert response.json() == {"accepted": 2}
    logs = _logs()
    assert len(logs) == 2
    assert {log.source for log in logs} == {"sdk"}
    assert logs[0].tenant_id == "acme"
    assert logs[0].condition == "own_team"
    assert logs[0].timestamp == 1_700_000_000.5


def test_batch_over_500_rejected(client: TestClient) -> None:
    response = client.post(
        f"{API}/access-logs/batch", json={"entries": [_entry()] * 501}
    )
    assert response.status_code == 422
    assert _logs() == []


def test_batch_empty_rejected(client: TestClient) -> None:
    response = client.post(f"{API}/access-logs/batch", json={"entries": []})
    assert response.status_code == 422


def test_batch_exactly_500_accepted(client: TestClient) -> None:
    response = client.post(
        f"{API}/access-logs/batch", json={"entries": [_entry()] * 500}
    )
    assert response.status_code == 202
    assert response.json() == {"accepted": 500}


def test_logs_env_scoped(client: TestClient) -> None:
    _check(client, environment="staging")
    client.post(
        f"{API}/access-logs/batch",
        json={"entries": [_entry()]},
        headers={"X-Osiki-Environment": "prod"},
    )
    assert _logs("default") == []
    assert len(_logs("staging")) == 1
    assert len(_logs("prod")) == 1
    assert _logs("prod")[0].environment_id == "prod"
