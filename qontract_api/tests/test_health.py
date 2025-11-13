"""Tests for health check endpoints."""

# ruff: noqa: ARG001 - Test code exceptions

from http import HTTPStatus

from fastapi.testclient import TestClient


def test_root_endpoint(client: TestClient) -> None:
    """Test root endpoint returns basic info."""
    response = client.get("/")
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


def test_liveness_probe(client: TestClient) -> None:
    """Test liveness probe endpoint."""
    response = client.get("/health/live")
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == "healthy"


def test_readiness_probe_without_cache(client: TestClient) -> None:
    """Test readiness probe fails when cache is not initialized."""
    response = client.get("/health/ready")
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    # Without cache initialized, should be degraded/unhealthy
    assert data["status"] in {"degraded", "unhealthy"}
    assert "components" in data
    assert "cache" in data["components"]


def test_readiness_probe_with_cache(client: TestClient, mock_cache: None) -> None:
    """Test readiness probe succeeds when cache is healthy."""
    response = client.get("/health/ready")
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == "healthy"
    assert data["components"]["cache"]["status"] == "healthy"


def test_health_endpoint(client: TestClient, mock_cache: None) -> None:
    """Test detailed health endpoint."""
    response = client.get("/health")
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "status" in data
    assert "service" in data
    assert "version" in data
    assert "components" in data
    assert "cache" in data["components"]
