"""Tests for OCM external API router endpoint."""

from collections.abc import Generator
from http import HTTPStatus
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from qontract_api.auth import create_access_token
from qontract_api.external.ocm.ocm_workspace_client import OcmClusterRecord
from qontract_api.models import TokenData


@pytest.fixture
def api_client() -> Generator[TestClient]:
    """Create test client with mocked cache and secret_manager."""
    from qontract_api.main import app

    app.state.cache = Mock()
    app.state.secret_manager = Mock()

    yield TestClient(app, raise_server_exceptions=False)

    if hasattr(app.state, "cache"):
        del app.state.cache
    if hasattr(app.state, "secret_manager"):
        del app.state.secret_manager


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Create authentication headers with valid JWT token."""
    token_data = TokenData(sub="testuser")
    test_token = create_access_token(data=token_data)
    return {"Authorization": f"Bearer {test_token}"}


OCM_CLUSTERS_ENDPOINT = "/api/v1/external/ocm/clusters"

BASE_PARAMS = {
    "secret_manager_url": "https://vault.example.com",
    "path": "secret/ocm/env",
    "field": "client_secret",
    "ocm_url": "https://api.openshift.com",
    "access_token_url": "https://sso.redhat.com/token",
    "access_token_client_id": "client-id",
    "label_key_prefix": "sre-capabilities.rhidp",
}


@patch("qontract_api.external.ocm.router.create_ocm_workspace_client")
def test_get_clusters_returns_response(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test GET /clusters returns discovered clusters."""
    mock_client = MagicMock()
    mock_client.get_clusters.return_value = [
        OcmClusterRecord(
            id="cluster-1",
            name="my-cluster",
            organization_id="org-1",
            console_url="https://console.example.com",
            external_auth_enabled=False,
            labels={"sre-capabilities.rhidp.name": "rhidp1"},
        )
    ]
    mock_factory.return_value = mock_client

    response = api_client.get(
        OCM_CLUSTERS_ENDPOINT, params=BASE_PARAMS, headers=auth_headers
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert len(data["clusters"]) == 1
    cluster = data["clusters"][0]
    assert cluster["id"] == "cluster-1"
    assert cluster["organization_id"] == "org-1"
    assert cluster["labels"] == {"sre-capabilities.rhidp.name": "rhidp1"}


@patch("qontract_api.external.ocm.router.create_ocm_workspace_client")
def test_get_clusters_passes_query_params_to_factory(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test GET /clusters passes query params to the factory correctly."""
    mock_client = MagicMock()
    mock_client.get_clusters.return_value = []
    mock_factory.return_value = mock_client

    api_client.get(OCM_CLUSTERS_ENDPOINT, params=BASE_PARAMS, headers=auth_headers)

    mock_factory.assert_called_once()
    params = mock_factory.call_args.kwargs["params"]
    assert params.ocm_url == "https://api.openshift.com"
    assert params.access_token_client_id == "client-id"
    assert params.label_key_prefix == "sre-capabilities.rhidp"


@patch("qontract_api.external.ocm.router.create_ocm_workspace_client")
def test_get_clusters_org_ids_query_param_roundtrip(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test org_ids list query param round-trips correctly to get_clusters()."""
    mock_client = MagicMock()
    mock_client.get_clusters.return_value = []
    mock_factory.return_value = mock_client

    api_client.get(
        OCM_CLUSTERS_ENDPOINT,
        params={**BASE_PARAMS, "org_ids": ["org-1", "org-2"]},
        headers=auth_headers,
    )

    mock_client.get_clusters.assert_called_once()
    call_kwargs = mock_client.get_clusters.call_args.kwargs
    assert call_kwargs["org_ids"] == {"org-1", "org-2"}


@patch("qontract_api.external.ocm.router.create_ocm_workspace_client")
def test_get_clusters_org_ids_omitted_passes_none(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test org_ids omitted from the request passes None to get_clusters()."""
    mock_client = MagicMock()
    mock_client.get_clusters.return_value = []
    mock_factory.return_value = mock_client

    api_client.get(OCM_CLUSTERS_ENDPOINT, params=BASE_PARAMS, headers=auth_headers)

    call_kwargs = mock_client.get_clusters.call_args.kwargs
    assert call_kwargs["org_ids"] is None


@patch("qontract_api.external.ocm.router.create_ocm_workspace_client")
def test_get_clusters_empty_result(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test GET /clusters with no matching clusters returns an empty list."""
    mock_client = MagicMock()
    mock_client.get_clusters.return_value = []
    mock_factory.return_value = mock_client

    response = api_client.get(
        OCM_CLUSTERS_ENDPOINT, params=BASE_PARAMS, headers=auth_headers
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["clusters"] == []
