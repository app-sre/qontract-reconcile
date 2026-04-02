"""Tests for API endpoints."""

from http import HTTPStatus
from unittest.mock import patch

from fastapi.testclient import TestClient

from qontract_api.auth import create_access_token
from qontract_api.models import TokenData


def test_protected_endpoint_without_token(client: TestClient) -> None:
    """Test protected endpoint returns 403 without token."""
    response = client.get("/api/protected")
    assert response.status_code == HTTPStatus.FORBIDDEN


def test_protected_endpoint_with_invalid_token(client: TestClient) -> None:
    """Test protected endpoint returns 401 with invalid token."""
    response = client.get(
        "/api/protected", headers={"Authorization": "Bearer invalid-token"}
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    data = response.json()
    assert "detail" in data


def test_protected_endpoint_with_valid_token(client: TestClient) -> None:
    """Test protected endpoint returns 200 with valid token."""
    token_data = TokenData(sub="testuser")
    token = create_access_token(data=token_data)

    response = client.get(
        "/api/protected", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["message"] == "Access granted"
    assert data["username"] == "testuser"


def test_protected_endpoint_with_revoked_subject(client: TestClient) -> None:
    """Test protected endpoint returns 401 when JWT subject is revoked."""
    token_data = TokenData(sub="revoked-user")
    token = create_access_token(data=token_data)

    with patch(
        "qontract_api.dependencies.settings.jwt_revoked_subjects",
        ["revoked-user"],
    ):
        response = client.get(
            "/api/protected", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    data = response.json()
    assert "revoked" in data["detail"]
