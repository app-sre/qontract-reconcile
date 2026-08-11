"""Tests for middleware."""

import gzip
import json
import zlib
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect

import qontract_api.middleware as middleware_module
from qontract_api.auth import create_access_token
from qontract_api.constants import REQUEST_ID_HEADER
from qontract_api.middleware import _decompress_gzip_bounded, _read_compressed_body
from qontract_api.models import TokenData


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


def test_gzip_request_decompression(
    client_with_cache: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that gzip-compressed requests are properly decompressed."""
    # Mock the Celery task to avoid actual task execution
    from unittest.mock import MagicMock

    import qontract_api.integrations.slack_usergroups.router as router_module

    mock_task = MagicMock()
    mock_task.delay.return_value.id = "test-task-id-123"
    monkeypatch.setattr(router_module, "reconcile_slack_usergroups_task", mock_task)

    # Create a valid token
    token_data = TokenData(sub="testuser")
    token = create_access_token(data=token_data)

    # Create test payload (no execution_mode - API is async-only now)
    payload = {
        "workspaces": [],  # Empty to avoid actual Slack API calls
        "dry_run": True,
    }

    # Compress payload
    json_data = json.dumps(payload)
    compressed = gzip.compress(json_data.encode("utf-8"))

    # Send compressed request
    response = client_with_cache.post(
        "/api/v1/integrations/slack-usergroups/reconcile",
        content=compressed,  # Use content= for raw bytes
        headers={
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
            "Authorization": f"Bearer {token}",
        },
    )

    # Should successfully decompress and process (POST always returns 202 Accepted)
    assert response.status_code == HTTPStatus.ACCEPTED  # 202 for async-only API
    data = response.json()
    assert "id" in data
    assert "status_url" in data
    assert data["status"] == "pending"  # TaskStatus.PENDING


def test_gzip_request_with_invalid_data(client_with_cache: TestClient) -> None:
    """Test that invalid gzip data returns 400 error."""
    token_data = TokenData(sub="testuser")
    token = create_access_token(data=token_data)

    # Send invalid gzip data
    invalid_gzip = b"not gzip data"

    response = client_with_cache.post(
        "/api/v1/integrations/slack-usergroups/reconcile",
        content=invalid_gzip,  # Use content= for raw bytes
        headers={
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
            "Authorization": f"Bearer {token}",
        },
    )

    # Should return 400 Bad Request
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "gzip" in response.text.lower()


def test_gzip_request_exceeds_max_compressed_size(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that an oversized compressed request body is rejected before decompression."""
    monkeypatch.setattr(middleware_module, "MAX_GZIP_COMPRESSED_SIZE", 1_000)

    # Body itself doesn't need to be valid gzip - the size check runs
    # while collecting chunks, before gzip decompression is attempted.
    oversized_body = b"x" * 2_000

    response = client.post(
        "/api/v1/integrations/slack-usergroups/reconcile",
        content=oversized_body,
        headers={
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
        },
    )

    assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    assert "compressed" in response.text.lower()


def test_gzip_bomb_exceeds_max_decompressed_size(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that a gzip bomb (small compressed, huge decompressed) is rejected."""
    monkeypatch.setattr(middleware_module, "MAX_GZIP_DECOMPRESSED_SIZE", 1_024)

    # Highly compressible payload: tiny compressed size, large decompressed size.
    bomb = gzip.compress(b"A" * 100_000)

    response = client.post(
        "/api/v1/integrations/slack-usergroups/reconcile",
        content=bomb,
        headers={
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
        },
    )

    assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    assert "decompress" in response.text.lower()


@pytest.mark.asyncio
async def test_read_compressed_body_raises_on_client_disconnect() -> None:
    """Test that an http.disconnect message raises ClientDisconnect instead of looping forever."""

    async def fake_receive() -> dict[str, object]:  # ruff: ignore[unused-async]
        return {"type": "http.disconnect"}

    with pytest.raises(ClientDisconnect):
        await _read_compressed_body(fake_receive, max_compressed_size=1_000)


def test_decompress_gzip_bounded_concatenated_members() -> None:
    """Test that concatenated gzip members are all decompressed, like gzip.decompress()."""
    payload = gzip.compress(b"first") + gzip.compress(b"second")

    result = _decompress_gzip_bounded(payload, max_decompressed_size=1_000)

    assert result == b"firstsecond"


def test_decompress_gzip_bounded_truncated_data() -> None:
    """Test that truncated gzip input raises instead of silently returning partial data."""
    truncated = gzip.compress(b"first")[:-8]

    with pytest.raises(gzip.BadGzipFile):
        _decompress_gzip_bounded(truncated, max_decompressed_size=1_000)


def test_decompress_gzip_bounded_trailing_garbage() -> None:
    """Test that trailing non-gzip data after a valid member raises instead of being dropped.

    Raises zlib.error (from parsing the invalid gzip header of the trailing
    data) rather than gzip.BadGzipFile - the middleware's dispatch() already
    catches both identically and maps them to a 400 "Invalid gzip data" response.
    """
    payload = gzip.compress(b"first") + b"garbage-not-gzip"

    with pytest.raises((gzip.BadGzipFile, zlib.error)):
        _decompress_gzip_bounded(payload, max_decompressed_size=1_000)


def test_uncompressed_request_still_works(
    client_with_cache: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that uncompressed requests still work normally."""
    # Mock the Celery task to avoid actual task execution
    from unittest.mock import MagicMock

    import qontract_api.integrations.slack_usergroups.router as router_module

    mock_task = MagicMock()
    mock_task.delay.return_value.id = "test-task-id-456"
    monkeypatch.setattr(router_module, "reconcile_slack_usergroups_task", mock_task)

    token_data = TokenData(sub="testuser")
    token = create_access_token(data=token_data)

    payload = {
        "workspaces": [],  # Empty to avoid actual Slack API calls
        "dry_run": True,
    }

    # Send uncompressed request (no Content-Encoding header)
    response = client_with_cache.post(
        "/api/v1/integrations/slack-usergroups/reconcile",
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
        },
    )

    # Should work normally (API is async-only, returns 202)
    assert response.status_code == HTTPStatus.ACCEPTED
    data = response.json()
    assert "id" in data
    assert "status_url" in data
