"""Tests for Internal Groups OAuth token fetch (Layer 1)."""

from __future__ import annotations

import httpx2
import pytest
from pytest_httpserver import HTTPServer
from qontract_utils.internal_groups_api.api import _fetch_access_token


def test_fetch_access_token_posts_credentials(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/token", method="POST").respond_with_json(
        {"access_token": "tok-123", "token_type": "bearer"}
    )
    token = _fetch_access_token(
        token_url=httpserver.url_for("/token"),
        client_id="cid",
        client_secret="sec",
        timeout=5.0,
    )
    assert token == "tok-123"
    request = httpserver.log[0][0]
    body = request.get_data(as_text=True)
    assert "grant_type=client_credentials" in body
    assert "client_id=cid" in body
    assert "client_secret=sec" in body


def test_fetch_access_token_propagates_auth_error(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/token", method="POST").respond_with_data(
        '{"error":"unauthorized"}',
        status=401,
    )
    with pytest.raises(httpx2.HTTPStatusError):
        _fetch_access_token(
            token_url=httpserver.url_for("/token"),
            client_id="cid",
            client_secret="sec",
            timeout=5.0,
        )


def test_fetch_access_token_respects_timeout(
    httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: list[tuple[float, httpx2.HTTPTransport]] = []

    class _RecordingClient(httpx2.Client):
        def __init__(self, *, timeout: float, transport: httpx2.HTTPTransport) -> None:
            recorded.append((timeout, transport))
            super().__init__(timeout=timeout, transport=transport)

    monkeypatch.setattr(httpx2, "Client", _RecordingClient)
    httpserver.expect_request("/token", method="POST").respond_with_json(
        {"access_token": "t"}
    )
    _fetch_access_token(
        token_url=httpserver.url_for("/token"),
        client_id="cid",
        client_secret="sec",
        timeout=12.5,
        max_retries=2,
    )
    timeout, transport = recorded[0]
    assert timeout == 12.5
    assert isinstance(transport, httpx2.HTTPTransport)
