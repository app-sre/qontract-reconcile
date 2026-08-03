"""Typed exceptions for Kubernetes API errors.

Maps lightkube ApiError status codes to specific exception subclasses
for clean error handling in Layer 1 client code.
"""

from lightkube import ApiError


class KubernetesApiError(Exception):
    """Base exception for Kubernetes API errors."""

    def __init__(self, *, code: int, reason: str, message: str) -> None:
        self.code = code
        self.reason = reason
        self.message = message
        super().__init__(f"{code} {reason}: {message}")


class NotFoundError(KubernetesApiError):
    """Resource not found (HTTP 404)."""


class AlreadyExistsError(KubernetesApiError):
    """Resource already exists (HTTP 409)."""


class ForbiddenError(KubernetesApiError):
    """Access forbidden (HTTP 403)."""


class UnauthorizedError(KubernetesApiError):
    """Authentication failed (HTTP 401)."""


_STATUS_CODE_MAP: dict[int, type[KubernetesApiError]] = {
    401: UnauthorizedError,
    403: ForbiddenError,
    404: NotFoundError,
    409: AlreadyExistsError,
}


def from_api_error(error: ApiError) -> KubernetesApiError:
    """Map a lightkube ApiError to a typed KubernetesApiError.

    Args:
        error: The lightkube ApiError to convert.

    Returns:
        A specific KubernetesApiError subclass based on the status code.
    """
    status = error.status
    code = status.code or 0
    reason = status.reason or "Unknown"
    message = status.message or str(error)
    exc_class = _STATUS_CODE_MAP.get(code, KubernetesApiError)
    exc = exc_class(code=code, reason=reason, message=message)
    exc.__cause__ = error
    return exc
