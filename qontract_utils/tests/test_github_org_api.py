"""Tests for qontract_utils.github_org.api."""

from pytest_httpserver import HTTPServer
from qontract_utils.github_org.api import GithubOrgApi

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
