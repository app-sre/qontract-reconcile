"""Tests for qontract_utils.kubernetes.exceptions module."""

from unittest.mock import MagicMock

import pytest
from lightkube import ApiError
from qontract_utils.kubernetes.exceptions import (
    AlreadyExistsError,
    ForbiddenError,
    KubernetesApiError,
    NotFoundError,
    UnauthorizedError,
    from_api_error,
)


def _make_api_error(code: int, reason: str, message: str) -> ApiError:
    """Create a lightkube ApiError with a mock response returning K8s status JSON."""
    response = MagicMock()
    response.status_code = code
    response.json.return_value = {
        "kind": "Status",
        "apiVersion": "v1",
        "status": "Failure",
        "message": message,
        "reason": reason,
        "code": code,
    }
    return ApiError(response=response)


def test_base_error_attributes() -> None:
    err = KubernetesApiError(code=500, reason="InternalError", message="boom")
    assert err.code == 500
    assert err.reason == "InternalError"
    assert err.message == "boom"


def test_base_error_str() -> None:
    err = KubernetesApiError(code=500, reason="InternalError", message="boom")
    assert "500" in str(err)
    assert "boom" in str(err)


def test_base_error_is_exception() -> None:
    assert issubclass(KubernetesApiError, Exception)


@pytest.mark.parametrize(
    "exc_class",
    [NotFoundError, AlreadyExistsError, ForbiddenError, UnauthorizedError],
)
def test_subclass_hierarchy(exc_class: type) -> None:
    assert issubclass(exc_class, KubernetesApiError)


def test_not_found_attributes() -> None:
    err = NotFoundError(
        code=404, reason="NotFound", message='namespaces "foo" not found'
    )
    assert err.code == 404
    assert err.reason == "NotFound"


def test_already_exists_attributes() -> None:
    err = AlreadyExistsError(
        code=409, reason="AlreadyExists", message='namespaces "foo" already exists'
    )
    assert err.code == 409
    assert err.reason == "AlreadyExists"


@pytest.mark.parametrize(
    ("code", "reason", "message", "expected_type"),
    [
        (404, "NotFound", "not found", NotFoundError),
        (409, "AlreadyExists", "already exists", AlreadyExistsError),
        (403, "Forbidden", "forbidden", ForbiddenError),
        (401, "Unauthorized", "unauthorized", UnauthorizedError),
        (500, "InternalError", "internal", KubernetesApiError),
        (422, "Unprocessable", "invalid", KubernetesApiError),
    ],
)
def test_from_api_error(
    code: int, reason: str, message: str, expected_type: type
) -> None:
    """Test from_api_error maps ApiError status codes to correct exception types."""
    api_error = _make_api_error(code, reason, message)
    result = from_api_error(api_error)
    assert isinstance(result, expected_type)
    assert result.code == code
    assert result.reason == reason
    assert result.message == message


def test_from_api_error_preserves_original_as_cause() -> None:
    """Test that from_api_error chains the original ApiError as __cause__."""
    api_error = _make_api_error(404, "NotFound", "not found")
    result = from_api_error(api_error)
    assert result.__cause__ is api_error
