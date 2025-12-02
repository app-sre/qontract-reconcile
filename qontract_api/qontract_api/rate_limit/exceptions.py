"""Rate limiting exceptions."""

from qontract_api.exceptions import APIError


class RateLimitExceeded(APIError):  # noqa: N818 - "Exceeded" suffix is more descriptive than "Error" for rate limiting
    """Raised when rate limit is exceeded."""

    def __init__(self, message: str) -> None:
        """Initialize RateLimitExceeded exception with 429 status code."""
        super().__init__(message, status_code=429)
