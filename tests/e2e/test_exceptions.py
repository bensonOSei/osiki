from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from tests.e2e.conftest import API, app


def test_not_found_error_format(client: TestClient) -> None:
    fake_id = str(PydanticObjectId())
    response = client.get(f"{API}/users/{fake_id}")
    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "not_found"
    assert "message" in data
    assert "details" in data
    assert "request_id" in data


def test_conflict_error_format(client: TestClient) -> None:
    client.post(f"{API}/users", json={"external_id": "dup"})
    response = client.post(f"{API}/users", json={"external_id": "dup"})
    assert response.status_code == 409
    data = response.json()
    assert data["error"] == "conflict"
    assert "message" in data
    assert "details" in data
    assert "request_id" in data


def test_error_response_includes_request_id(client: TestClient) -> None:
    custom_id = "test-req-id-123"
    fake_id = str(PydanticObjectId())
    response = client.get(
        f"{API}/users/{fake_id}",
        headers={"X-Request-ID": custom_id},
    )
    assert response.status_code == 404
    assert response.json()["request_id"] == custom_id


def test_authorization_error(client: TestClient) -> None:
    response = client.get("/_test/authorization-error")
    assert response.status_code == 403
    data = response.json()
    assert data["error"] == "forbidden"
    assert data["message"] == "forbidden"
    assert data["details"] == {"reason": "test"}
    assert "request_id" in data


def test_validation_error(client: TestClient) -> None:
    response = client.get("/_test/validation-error")
    assert response.status_code == 422
    data = response.json()
    assert data["error"] == "validation_error"
    assert data["message"] == "invalid input"
    assert data["details"] == {"field": "test"}
    assert "request_id" in data


def test_internal_server_error() -> None:
    with TestClient(app, raise_server_exceptions=False) as c:
        response = c.get("/_test/internal-error")
    assert response.status_code == 500
    data = response.json()
    assert data["error"] == "internal_server_error"
    assert data["message"] == "An unexpected error occurred"
    assert "request_id" in data
