from fastapi.testclient import TestClient

from tests.e2e.conftest import API


def test_authorization_check_denied(client: TestClient) -> None:
    response = client.post(
        f"{API}/authorization/check",
        json={
            "user_id": "user-1",
            "resource": "documents",
            "action": "read",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["allowed"] is False
    assert data["denial_reason"] is not None


def test_authorization_check_with_scope(client: TestClient) -> None:
    response = client.post(
        f"{API}/authorization/check",
        json={
            "user_id": "user-1",
            "resource": "documents",
            "action": "read",
            "scope": {"tenant_id": "tenant-1"},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["allowed"] is False


def test_authorization_check_without_scope(client: TestClient) -> None:
    response = client.post(
        f"{API}/authorization/check",
        json={
            "user_id": "user-1",
            "resource": "documents",
            "action": "write",
        },
    )
    assert response.status_code == 200
    assert "allowed" in response.json()
    assert "denial_reason" in response.json()
