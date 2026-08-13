from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from reconcile.dashdotdb_base import (
    DashdotdbBase,
    DashdotdbTokenError,
)


def _make_base(dry_run: bool = False) -> DashdotdbBase:
    """Build a DashdotdbBase with stubbed-out secret reader."""
    secret_reader = MagicMock()
    secret_reader.read_all_secret.return_value = {
        "url": "https://dashdotdb.example.com",
        "username": "user",
        "password": "pass",
    }
    return DashdotdbBase(
        dry_run=dry_run,
        thread_pool_size=1,
        marker="TEST:",
        scope="test-scope",
        secret_reader=secret_reader,
    )


def _ok_response(token_text: str = '"  my-token  "') -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 200
    resp.text = token_text
    resp.raise_for_status = MagicMock()
    return resp


def _error_response(status: int = 401) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status
    resp.raise_for_status = MagicMock(
        side_effect=requests.exceptions.HTTPError(
            response=resp,
        )
    )
    return resp


@patch("reconcile.dashdotdb_base.requests.get")
@patch("reconcile.dashdotdb_base.requests.delete")
def test_dry_run_yields_none_with_no_http_activity(
    mock_delete: MagicMock,
    mock_get: MagicMock,
) -> None:
    base = _make_base(dry_run=True)

    with base._token() as token:
        assert token is None

    mock_get.assert_not_called()
    mock_delete.assert_not_called()


@patch("reconcile.dashdotdb_base.requests.get")
@patch("reconcile.dashdotdb_base.requests.delete")
def test_successful_acquisition_yields_token_and_releases(
    mock_delete: MagicMock,
    mock_get: MagicMock,
) -> None:
    mock_get.return_value = _ok_response('"  my-token  "')
    mock_delete.return_value = MagicMock(spec=requests.Response)
    mock_delete.return_value.raise_for_status = MagicMock()

    base = _make_base(dry_run=False)

    with base._token() as token:
        assert token == "my-token"
        assert base.dashdotdb_token == "my-token"

    mock_get.assert_called_once()
    mock_delete.assert_called_once()
    delete_url = mock_delete.call_args.kwargs.get(
        "url", mock_delete.call_args[1].get("url")
    )
    assert "my-token" in delete_url


@patch("reconcile.dashdotdb_base.requests.get")
@patch("reconcile.dashdotdb_base.requests.delete")
def test_failed_acquisition_raises_dashdotdb_token_error(
    mock_delete: MagicMock,
    mock_get: MagicMock,
) -> None:
    mock_get.return_value = _error_response(401)

    base = _make_base(dry_run=False)

    with pytest.raises(DashdotdbTokenError), base._token():
        pytest.fail("body should not execute after failed acquisition")

    mock_delete.assert_not_called()


@patch("reconcile.dashdotdb_base.requests.get")
@patch("reconcile.dashdotdb_base.requests.delete")
def test_failed_acquisition_does_not_attempt_token_release(
    mock_delete: MagicMock,
    mock_get: MagicMock,
) -> None:
    mock_get.return_value = _error_response(401)

    base = _make_base(dry_run=False)

    with pytest.raises(DashdotdbTokenError), base._token():
        pass

    mock_delete.assert_not_called()
    assert base.dashdotdb_token is None


@patch("reconcile.dashdotdb_base.requests.get")
@patch("reconcile.dashdotdb_base.requests.delete")
def test_body_exception_after_acquisition_still_releases_token(
    mock_delete: MagicMock,
    mock_get: MagicMock,
) -> None:
    mock_get.return_value = _ok_response('"valid-token"')
    mock_delete.return_value = MagicMock(spec=requests.Response)
    mock_delete.return_value.raise_for_status = MagicMock()

    base = _make_base(dry_run=False)

    with pytest.raises(RuntimeError, match="simulated failure"), base._token() as token:
        assert token == "valid-token"
        raise RuntimeError("simulated failure")

    mock_delete.assert_called_once()
