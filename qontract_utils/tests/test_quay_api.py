"""Tests for qontract_utils.quay_api module."""

from dataclasses import FrozenInstanceError
from typing import Any
from unittest.mock import MagicMock, patch

import httpx2
import pytest
from qontract_utils.hooks import Hooks
from qontract_utils.quay_api import TIMEOUT, QuayApi, QuayApiCallContext, QuayRepo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok_response(body: dict[str, Any] | None = None) -> MagicMock:
    response = MagicMock(spec=httpx2.Response)
    response.json.return_value = body or {}
    response.raise_for_status.return_value = None
    return response


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_httpx_client() -> MagicMock:
    return MagicMock(spec=httpx2.Client)


@pytest.fixture
def quay_api(mock_httpx_client: MagicMock) -> QuayApi:
    with patch("qontract_utils.quay_api.client.httpx2.Client") as mock_cls:
        mock_cls.return_value = mock_httpx_client
        return QuayApi(org="test-org", token="test-token")


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


def test_quay_api_stores_org() -> None:
    with patch("qontract_utils.quay_api.client.httpx2.Client"):
        api = QuayApi(org="my-org", token="tok")
    assert api.org == "my-org"


def test_quay_api_bearer_token_in_headers() -> None:
    with patch("qontract_utils.quay_api.client.httpx2.Client") as mock_cls:
        QuayApi(org="my-org", token="secret")
    _, kwargs = mock_cls.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer secret"


def test_quay_api_base_url_trailing_slash_stripped() -> None:
    with patch("qontract_utils.quay_api.client.httpx2.Client") as mock_cls:
        QuayApi(org="my-org", token="tok", base_url="https://quay.example.com/")
    _, kwargs = mock_cls.call_args
    assert kwargs["base_url"] == "https://quay.example.com"


def test_quay_api_base_url_no_protocol_gets_https() -> None:
    with patch("qontract_utils.quay_api.client.httpx2.Client") as mock_cls:
        QuayApi(org="my-org", token="tok", base_url="quay.io")
    _, kwargs = mock_cls.call_args
    assert kwargs["base_url"] == "https://quay.io"


def test_quay_api_rejects_http_base_url() -> None:
    with (
        patch("qontract_utils.quay_api.client.httpx2.Client") as mock_cls,
        pytest.raises(ValueError, match="must use HTTPS"),
    ):
        QuayApi(org="my-org", token="tok", base_url="http://quay.example.com")
    mock_cls.assert_not_called()


def test_quay_api_default_timeout() -> None:
    with patch("qontract_utils.quay_api.client.httpx2.Client") as mock_cls:
        QuayApi(org="my-org", token="tok")
    _, kwargs = mock_cls.call_args
    assert kwargs["timeout"] == TIMEOUT


def test_quay_api_custom_hooks_merged() -> None:
    custom_hook = MagicMock()
    with patch("qontract_utils.quay_api.client.httpx2.Client"):
        api = QuayApi(org="my-org", token="tok", hooks=Hooks(pre_hooks=[custom_hook]))
    # built-in: metrics + log + latency_start = 3; custom adds 1
    assert len(api._hooks.pre_hooks) >= 4


# ---------------------------------------------------------------------------
# list_images
# ---------------------------------------------------------------------------


def test_list_images_single_page(
    quay_api: QuayApi, mock_httpx_client: MagicMock
) -> None:
    mock_httpx_client.get.return_value = _ok_response(
        {
            "repositories": [
                {"name": "repo-a", "is_public": True, "description": "first"},
                {"name": "repo-b", "is_public": False, "description": ""},
            ]
        }
    )

    repos = quay_api.list_images()

    assert len(repos) == 2
    assert isinstance(repos[0], QuayRepo)
    assert repos[0].name == "repo-a"
    assert repos[0].is_public is True
    assert repos[1].is_public is False
    mock_httpx_client.get.assert_called_once_with(
        "/api/v1/repository", params={"namespace": "test-org"}
    )


def test_list_images_follows_pagination(
    quay_api: QuayApi, mock_httpx_client: MagicMock
) -> None:
    mock_httpx_client.get.side_effect = [
        _ok_response(
            {
                "repositories": [
                    {"name": "repo-a", "is_public": True, "description": ""}
                ],
                "next_page": "cursor-abc",
            }
        ),
        _ok_response(
            {
                "repositories": [
                    {"name": "repo-b", "is_public": False, "description": ""}
                ],
            }
        ),
    ]

    repos = quay_api.list_images()

    assert len(repos) == 2
    assert repos[0].name == "repo-a"
    assert repos[1].name == "repo-b"
    assert mock_httpx_client.get.call_count == 2
    second_params = mock_httpx_client.get.call_args_list[1][1]["params"]
    assert second_params["next_page"] == "cursor-abc"
    assert second_params["namespace"] == "test-org"


def test_list_images_empty_org(quay_api: QuayApi, mock_httpx_client: MagicMock) -> None:
    mock_httpx_client.get.return_value = _ok_response({"repositories": []})
    assert quay_api.list_images() == []


def test_list_images_coerces_null_description(
    quay_api: QuayApi, mock_httpx_client: MagicMock
) -> None:
    mock_httpx_client.get.return_value = _ok_response(
        {
            "repositories": [
                {
                    "name": "repo-a",
                    "is_public": True,
                    "description": None,
                    "namespace": "test-org",
                }
            ]
        }
    )

    repos = quay_api.list_images()

    assert len(repos) == 1
    assert repos[0].name == "repo-a"
    assert not repos[0].description


def test_list_images_raises_on_too_many_pages(
    quay_api: QuayApi, mock_httpx_client: MagicMock
) -> None:
    mock_httpx_client.get.return_value = _ok_response(
        {
            "repositories": [],
            "next_page": "forever",
        }
    )
    with pytest.raises(ValueError, match="page follows"):
        quay_api.list_images()


def test_list_images_propagates_http_error(
    quay_api: QuayApi, mock_httpx_client: MagicMock
) -> None:
    response = MagicMock(spec=httpx2.Response)
    response.raise_for_status.side_effect = httpx2.HTTPStatusError(
        "404", request=MagicMock(), response=MagicMock()
    )
    mock_httpx_client.get.return_value = response

    with pytest.raises(httpx2.HTTPStatusError):
        quay_api.list_images()


# ---------------------------------------------------------------------------
# repo_create
# ---------------------------------------------------------------------------


def test_repo_create_public(quay_api: QuayApi, mock_httpx_client: MagicMock) -> None:
    mock_httpx_client.post.return_value = _ok_response()

    quay_api.repo_create("my-repo", "a description", public=True)

    mock_httpx_client.post.assert_called_once_with(
        "/api/v1/repository",
        json={
            "repo_kind": "image",
            "namespace": "test-org",
            "visibility": "public",
            "repository": "my-repo",
            "description": "a description",
        },
    )


def test_repo_create_private(quay_api: QuayApi, mock_httpx_client: MagicMock) -> None:
    mock_httpx_client.post.return_value = _ok_response()

    quay_api.repo_create("my-repo", "", public=False)

    _, kwargs = mock_httpx_client.post.call_args
    assert kwargs["json"]["visibility"] == "private"


# ---------------------------------------------------------------------------
# repo_delete
# ---------------------------------------------------------------------------


def test_repo_delete(quay_api: QuayApi, mock_httpx_client: MagicMock) -> None:
    mock_httpx_client.delete.return_value = _ok_response()

    quay_api.repo_delete("my-repo")

    mock_httpx_client.delete.assert_called_once_with(
        "/api/v1/repository/test-org/my-repo"
    )


# ---------------------------------------------------------------------------
# repo_update_description
# ---------------------------------------------------------------------------


def test_repo_update_description(
    quay_api: QuayApi, mock_httpx_client: MagicMock
) -> None:
    mock_httpx_client.put.return_value = _ok_response()

    quay_api.repo_update_description("my-repo", "new description")

    mock_httpx_client.put.assert_called_once_with(
        "/api/v1/repository/test-org/my-repo",
        json={"description": "new description"},
    )


# ---------------------------------------------------------------------------
# repo_make_public / repo_make_private
# ---------------------------------------------------------------------------


def test_repo_make_public(quay_api: QuayApi, mock_httpx_client: MagicMock) -> None:
    mock_httpx_client.post.return_value = _ok_response()

    quay_api.repo_make_public("my-repo")

    mock_httpx_client.post.assert_called_once_with(
        "/api/v1/repository/test-org/my-repo/changevisibility",
        json={"visibility": "public"},
    )


def test_repo_make_private(quay_api: QuayApi, mock_httpx_client: MagicMock) -> None:
    mock_httpx_client.post.return_value = _ok_response()

    quay_api.repo_make_private("my-repo")

    mock_httpx_client.post.assert_called_once_with(
        "/api/v1/repository/test-org/my-repo/changevisibility",
        json={"visibility": "private"},
    )


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------


def test_close_closes_httpx_client(
    quay_api: QuayApi, mock_httpx_client: MagicMock
) -> None:
    quay_api.close()
    mock_httpx_client.close.assert_called_once()


def test_context_manager_closes_on_exit(
    quay_api: QuayApi, mock_httpx_client: MagicMock
) -> None:
    with quay_api as api:
        assert api.org == "test-org"
    mock_httpx_client.close.assert_called_once()


def test_context_manager_closes_on_exception(
    quay_api: QuayApi, mock_httpx_client: MagicMock
) -> None:
    with pytest.raises(ValueError, match="boom"), quay_api:
        raise ValueError("boom")
    mock_httpx_client.close.assert_called_once()


# ---------------------------------------------------------------------------
# QuayApiCallContext
# ---------------------------------------------------------------------------


def test_call_context_is_frozen() -> None:
    ctx = QuayApiCallContext(method="repository.list", verb="GET", org="my-org")
    with pytest.raises(FrozenInstanceError):
        ctx.method = "other"  # type: ignore[misc]
