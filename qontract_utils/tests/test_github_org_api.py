"""Tests for qontract_utils.github_org.api."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
import requests
from github.GithubException import GithubException, RateLimitExceededException
from github.NamedUser import NamedUser
from pytest_httpserver import HTTPServer
from qontract_utils.github_org.api import (
    _DEFAULT_RATE_LIMIT_FALLBACK_SECONDS,
    GithubOrgApi,
    GithubRateLimitExceededError,
)
from werkzeug import Response

INVITATIONS_PATH = "/orgs/my-org/invitations"


def test_default_user_agent_identifies_qontract_utils(httpserver: HTTPServer) -> None:
    api = GithubOrgApi(token="token", base_url=httpserver.url_for(""))
    httpserver.expect_request(INVITATIONS_PATH, method="GET").respond_with_json([])

    api.get_pending_invitations("my-org")

    request = next(req for req, _ in httpserver.log if req.path == INVITATIONS_PATH)
    assert request.headers["User-Agent"].startswith("qontract-utils/")


def test_custom_user_agent_overrides_default(httpserver: HTTPServer) -> None:
    api = GithubOrgApi(
        token="token",
        base_url=httpserver.url_for(""),
        user_agent="qontract-api/1.2.3",
    )
    httpserver.expect_request(INVITATIONS_PATH, method="GET").respond_with_json([])

    api.get_pending_invitations("my-org")

    request = next(req for req, _ in httpserver.log if req.path == INVITATIONS_PATH)
    assert request.headers["User-Agent"] == "qontract-api/1.2.3"


def test_paginated_get_raises_rate_limit_error_on_403_remaining_zero(
    httpserver: HTTPServer,
) -> None:
    api = GithubOrgApi(token="token", base_url=httpserver.url_for(""))
    reset_epoch = int(datetime(2026, 9, 4, 17, 22, 2, tzinfo=UTC).timestamp())
    httpserver.expect_request(INVITATIONS_PATH, method="GET").respond_with_json(
        {"message": "API rate limit exceeded"},
        status=403,
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset_epoch)},
    )

    with pytest.raises(GithubRateLimitExceededError) as exc_info:
        api.get_pending_invitations("my-org")

    assert exc_info.value.reset_at == datetime.fromtimestamp(reset_epoch, tz=UTC)


def test_paginated_get_raises_rate_limit_error_on_429(
    httpserver: HTTPServer,
) -> None:
    api = GithubOrgApi(token="token", base_url=httpserver.url_for(""))
    httpserver.expect_request(INVITATIONS_PATH, method="GET").respond_with_json(
        {"message": "secondary rate limit"},
        status=429,
        headers={"Retry-After": "30"},
    )

    before = datetime.now(UTC)
    with pytest.raises(GithubRateLimitExceededError) as exc_info:
        api.get_pending_invitations("my-org")
    after = datetime.now(UTC)

    assert (
        before + timedelta(seconds=30)
        <= exc_info.value.reset_at
        <= after + timedelta(seconds=30)
    )


def test_paginated_get_403_without_ratelimit_raises_httperror(
    httpserver: HTTPServer,
) -> None:
    api = GithubOrgApi(token="token", base_url=httpserver.url_for(""))
    httpserver.expect_request(INVITATIONS_PATH, method="GET").respond_with_json(
        {"message": "Forbidden"},
        status=403,
        headers={"X-RateLimit-Remaining": "42"},
    )

    with pytest.raises(requests.HTTPError):
        api.get_pending_invitations("my-org")


def test_get_admin_members_raises_rate_limit_error() -> None:
    api = GithubOrgApi(token="token", base_url="https://api.github.com")
    reset_epoch = 1788542522
    org = MagicMock()
    org.get_members.side_effect = RateLimitExceededException(
        403, {"message": "rate limit"}, {"x-ratelimit-reset": str(reset_epoch)}
    )
    api._gh = MagicMock()
    api._gh.get_organization.return_value = org

    with pytest.raises(GithubRateLimitExceededError) as exc_info:
        api.get_admin_members("my-org")

    assert exc_info.value.reset_at == datetime.fromtimestamp(reset_epoch, tz=UTC)


def test_add_member_as_admin_raises_rate_limit_error_on_429() -> None:
    api = GithubOrgApi(token="token", base_url="https://api.github.com")
    org = MagicMock()
    org.add_to_members.side_effect = GithubException(
        429, {"message": "secondary rate limit"}, {"retry-after": "15"}
    )
    api._gh = MagicMock()
    api._gh.get_organization.return_value = org
    api._gh.get_user.return_value = MagicMock(spec=NamedUser)

    before = datetime.now(UTC)
    with pytest.raises(GithubRateLimitExceededError) as exc_info:
        api.add_member_as_admin("my-org", "alice")
    after = datetime.now(UTC)

    assert (
        before + timedelta(seconds=15)
        <= exc_info.value.reset_at
        <= after + timedelta(seconds=15)
    )


def test_reset_at_fallback_when_headers_missing() -> None:
    api = GithubOrgApi(token="token", base_url="https://api.github.com")
    org = MagicMock()
    org.get_members.side_effect = RateLimitExceededException(
        403, {"message": "rate limit"}, {}
    )
    api._gh = MagicMock()
    api._gh.get_organization.return_value = org

    before = datetime.now(UTC)
    with pytest.raises(GithubRateLimitExceededError) as exc_info:
        api.get_admin_members("my-org")
    after = datetime.now(UTC)

    fallback = timedelta(seconds=_DEFAULT_RATE_LIMIT_FALLBACK_SECONDS)
    assert before + fallback <= exc_info.value.reset_at <= after + fallback


@pytest.mark.usefixtures("enable_retry")
def test_rate_limit_is_not_retried(httpserver: HTTPServer) -> None:
    """A rate-limited request must fail on the first attempt, never retried."""
    api = GithubOrgApi(token="token", base_url=httpserver.url_for(""))
    httpserver.expect_request(INVITATIONS_PATH, method="GET").respond_with_json(
        {"message": "API rate limit exceeded"},
        status=403,
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9999999999"},
    )

    with pytest.raises(GithubRateLimitExceededError):
        api.get_pending_invitations("my-org")

    assert len(httpserver.log) == 1


@pytest.mark.usefixtures("enable_retry")
def test_transient_server_error_is_retried_then_succeeds(
    httpserver: HTTPServer,
) -> None:
    """A transient 503 must be retried and the call must succeed once it clears.

    `enable_retry` forces exactly 3 attempts (see tests/conftest.py), so the
    handler is written to succeed on the 3rd call regardless of
    `_RETRY_CONFIG.attempts`.
    """
    call_count = {"n": 0}

    def handler(_request: object) -> Response:
        call_count["n"] += 1
        if call_count["n"] < 3:
            return Response(status=503)
        return Response(response="[]", content_type="application/json")

    httpserver.expect_request(INVITATIONS_PATH, method="GET").respond_with_handler(
        handler
    )
    api = GithubOrgApi(token="token", base_url=httpserver.url_for(""))

    result = api.get_pending_invitations("my-org")

    assert result == []
    assert call_count["n"] == 3


@pytest.mark.usefixtures("enable_retry")
def test_persistent_server_error_exhausts_retries_and_raises(
    httpserver: HTTPServer,
) -> None:
    """A persistent 503 must be retried up to the configured limit, then raise."""
    api = GithubOrgApi(token="token", base_url=httpserver.url_for(""))
    httpserver.expect_request(INVITATIONS_PATH, method="GET").respond_with_json(
        {"message": "Service Unavailable"}, status=503
    )

    with pytest.raises(requests.HTTPError):
        api.get_pending_invitations("my-org")

    assert len(httpserver.log) == 3


@pytest.mark.usefixtures("enable_retry")
def test_transient_connection_error_is_retried_and_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A network-level connection error must be retried, not fail immediately."""
    api = GithubOrgApi(token="token", base_url="https://api.github.com")
    call_count = {"n": 0}

    def flaky_get(*_args: object, **_kwargs: object) -> requests.Response:
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise requests.ConnectionError("connection reset by peer")
        response = requests.Response()
        response.status_code = 200
        response._content = b"[]"
        return response

    monkeypatch.setattr("qontract_utils.github_org.api.requests.get", flaky_get)

    result = api.get_pending_invitations("my-org")

    assert result == []
    assert call_count["n"] == 2


@pytest.mark.usefixtures("enable_retry")
def test_persistent_connection_error_exhausts_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A persistent connection error must exhaust retries, then propagate."""
    api = GithubOrgApi(token="token", base_url="https://api.github.com")
    call_count = {"n": 0}

    def always_fails(*_args: object, **_kwargs: object) -> requests.Response:
        call_count["n"] += 1
        raise requests.ConnectionError("connection reset by peer")

    monkeypatch.setattr("qontract_utils.github_org.api.requests.get", always_fails)

    with pytest.raises(requests.ConnectionError):
        api.get_pending_invitations("my-org")

    assert call_count["n"] == 3


@pytest.mark.usefixtures("enable_retry")
def test_transient_pygithub_server_error_is_retried_and_succeeds() -> None:
    """A 5xx GithubException from PyGithub must be retried, not fail immediately."""
    api = GithubOrgApi(token="token", base_url="https://api.github.com")
    member = MagicMock()
    member.login = "Alice"
    org = MagicMock()
    org.get_members.side_effect = [
        GithubException(502, {"message": "Bad Gateway"}, {}),
        [member],
    ]
    api._gh = MagicMock()
    api._gh.get_organization.return_value = org

    result = api.get_admin_members("my-org")

    assert result == ["alice"]
    assert org.get_members.call_count == 2
