"""Tests for exception handling."""

from http import HTTPStatus

from fastapi.testclient import TestClient

from qontract_api.exceptions import (
    APIError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)


def test_api_error() -> None:
    """Test APIError base class."""
    error = APIError("Test error", status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
    assert error.message == "Test error"
    assert error.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


def test_not_found_error() -> None:
    """Test NotFoundError."""
    error = NotFoundError("Item not found")
    assert error.message == "Item not found"
    assert error.status_code == HTTPStatus.NOT_FOUND


def test_validation_error() -> None:
    """Test ValidationError."""
    error = ValidationError("Invalid input")
    assert error.message == "Invalid input"
    assert error.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_unauthorized_error() -> None:
    """Test UnauthorizedError."""
    error = UnauthorizedError("Not authorized")
    assert error.message == "Not authorized"
    assert error.status_code == HTTPStatus.UNAUTHORIZED


def test_error_handler_via_endpoint(client: TestClient) -> None:
    """Test error handler is triggered via exception in endpoint."""
    # Test via protected endpoint with invalid token (triggers HTTPException -> error handler)
    response = client.get(
        "/api/protected", headers={"Authorization": "Bearer invalid-token"}
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    data = response.json()
    assert "detail" in data
