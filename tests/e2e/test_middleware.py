import uuid
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from osiki.api.middleware.request_id import get_request_id


def test_request_id_generated(client: TestClient) -> None:
    response = client.get("/health")
    assert "x-request-id" in response.headers
    # Should be a valid UUID
    uuid.UUID(response.headers["x-request-id"])


def test_get_request_id_fallback() -> None:
    request = MagicMock()
    del request.state.request_id
    result = get_request_id(request)
    # Should return a valid UUID when no request_id on state
    uuid.UUID(result)


def test_request_id_passthrough(client: TestClient) -> None:
    custom_id = "my-custom-request-id"
    response = client.get("/health", headers={"X-Request-ID": custom_id})
    assert response.headers["x-request-id"] == custom_id


def test_request_id_on_error_response(client: TestClient) -> None:
    response = client.get("/api/v1/users/nonexistent-id")
    assert "x-request-id" in response.headers
