"""Tests for PagerDuty external API router error handling."""

from collections.abc import Generator
from http import HTTPStatus
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from pagerduty import HttpError

from qontract_api.auth import create_access_token
from qontract_api.models import TokenData


@pytest.fixture
def api_client() -> Generator[TestClient]:
    """Provide dependencies required by the PagerDuty router without I/O."""
    from qontract_api.main import app

    app.state.cache = Mock()
    app.state.secret_manager = Mock()
    yield TestClient(app, raise_server_exceptions=False)
    del app.state.cache
    del app.state.secret_manager


def test_missing_schedule_returns_request_correlated_not_found(
    api_client: TestClient,
) -> None:
    """A deleted schedule is distinguishable from an internal API failure."""
    workspace_client = MagicMock()
    workspace_client.get_schedule_users.side_effect = HttpError(
        "Schedule Not Found", MagicMock(status_code=404)
    )
    token = create_access_token(data=TokenData(sub="testuser"))

    with patch(
        "qontract_api.external.pagerduty.router.create_pagerduty_workspace_client",
        return_value=workspace_client,
    ):
        response = api_client.get(
            "/api/v1/external/pagerduty/schedules/PTA0024/users",
            params={
                "secret_manager_url": "https://vault.example.com",
                "path": "secret/pagerduty",
                "field": "token",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["message"] == "PagerDuty schedule 'PTA0024' was not found"
    assert response.json()["type"] == "NotFoundError"
    assert response.json()["request_id"]
