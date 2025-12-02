"""Tests for health check endpoints."""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from qontract_api.health import HealthStatus


def test_root_endpoint(client: TestClient) -> None:
    """Test root endpoint returns basic info."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == HTTPStatus.TEMPORARY_REDIRECT


def test_liveness_probe(client: TestClient) -> None:
    """Test liveness probe endpoint."""
    response = client.get("/health/live")
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == "healthy"


@patch("qontract_api.tasks.health.health_check")
def test_readiness_probe_without_cache(
    mock_health_check: MagicMock, client: TestClient
) -> None:
    """Test readiness probe fails when cache is not initialized."""
    # Mock worker health check to succeed
    mock_result = MagicMock()
    mock_result.wait.return_value = HealthStatus(
        status="healthy", message="Celery worker is operational"
    )
    mock_health_check.delay.return_value = mock_result

    response = client.get("/health/ready")
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    # Without cache initialized, should be degraded/unhealthy
    assert data["status"] in {"degraded", "unhealthy"}
    assert "components" in data
    assert "cache" in data["components"]


@patch("qontract_api.tasks.health.health_check")
def test_readiness_probe_with_cache(
    mock_health_check: MagicMock, client_with_cache: TestClient
) -> None:
    """Test readiness probe succeeds when cache is healthy."""
    # Mock worker health check to succeed
    mock_result = MagicMock()
    mock_result.wait.return_value = HealthStatus(
        status="healthy", message="Celery worker is operational"
    )
    mock_health_check.delay.return_value = mock_result

    response = client_with_cache.get("/health/ready")
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == "healthy"
    assert data["components"]["cache"]["status"] == "healthy"
    assert data["components"]["worker"]["status"] == "healthy"
