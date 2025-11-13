"""Tests for middleware."""

from http import HTTPStatus

from fastapi.testclient import TestClient

from qontract_api.constants import REQUEST_ID_HEADER


def test_request_id_middleware(client: TestClient) -> None:
    """Test that X-Request-ID header is added to responses."""
    response = client.get("/")
    assert response.status_code == HTTPStatus.OK
    assert REQUEST_ID_HEADER in response.headers
    assert len(response.headers[REQUEST_ID_HEADER]) > 0


def test_request_id_is_unique(client: TestClient) -> None:
    """Test that each request gets a unique request ID."""
    response1 = client.get("/")
    response2 = client.get("/")

    request_id_1 = response1.headers[REQUEST_ID_HEADER]
    request_id_2 = response2.headers[REQUEST_ID_HEADER]

    assert request_id_1 != request_id_2
