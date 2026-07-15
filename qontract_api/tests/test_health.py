"""Tests for health check endpoints."""

from http import HTTPStatus
from unittest.mock import Mock

import httpx2
import pytest
from fastapi.testclient import TestClient

from qontract_api.health import check_opa_health
from qontract_api.opa import OPAClient


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


def test_readiness_probe_without_cache(client: TestClient) -> None:
    """Test readiness probe fails when cache is not initialized."""
    response = client.get("/health/ready")
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    # Without cache initialized, should be degraded/unhealthy
    assert data["status"] in {"degraded", "unhealthy"}
    assert "components" in data
    assert "cache" in data["components"]


def test_readiness_probe_with_cache(client_with_cache: TestClient) -> None:
    """Test readiness probe succeeds when cache is healthy."""
    response = client_with_cache.get("/health/ready")
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == "healthy"
    assert data["components"]["cache"]["status"] == "healthy"


def test_check_opa_health_connection_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refused OPA connection should report unhealthy, not raise."""

    def raise_connect_error(*args: object, **kwargs: object) -> None:
        raise httpx2.ConnectError("connection refused")

    monkeypatch.setattr(httpx2, "get", raise_connect_error)
    opa_client = Mock(spec=OPAClient)
    opa_client.health_url = "http://opa:8181/health"

    result = check_opa_health(opa_client)

    assert result.status == "unhealthy"
    assert result.message is not None
    assert "connection refused" in result.message
