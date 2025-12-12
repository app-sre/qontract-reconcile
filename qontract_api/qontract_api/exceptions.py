"""Custom exceptions and error handlers for qontract-api."""

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from qontract_api.logger import get_logger

log = get_logger(__name__)


class ErrorDetail(BaseModel):
    """Error detail model."""

    message: str = Field(..., description="Error message")
    type: str = Field(..., description="Error type")
    request_id: str | None = Field(None, description="Request ID for tracking")


class APIError(Exception):
    """Base exception for API errors."""

    def __init__(
        self, message: str, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    ) -> None:
        """Initialize API error."""
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class NotFoundError(APIError):
    """Resource not found error."""

    def __init__(self, message: str = "Resource not found") -> None:
        """Initialize not found error."""
        super().__init__(message, status_code=status.HTTP_404_NOT_FOUND)


class ValidationError(APIError):
    """Validation error."""

    def __init__(self, message: str) -> None:
        """Initialize validation error."""
        super().__init__(message, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


class UnauthorizedError(APIError):
    """Unauthorized error."""

    def __init__(self, message: str = "Unauthorized") -> None:
        """Initialize unauthorized error."""
        super().__init__(message, status_code=status.HTTP_401_UNAUTHORIZED)


async def api_error_handler(  # noqa: RUF029 - FastAPI requires async exception handlers
    request: Request, exc: APIError
) -> JSONResponse:
    """Handle APIError exceptions."""
    request_id = getattr(request.state, "request_id", None)
    error_detail = ErrorDetail(
        message=exc.message,
        type=exc.__class__.__name__,
        request_id=request_id,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_detail.model_dump(),
    )


async def general_exception_handler(  # noqa: RUF029 - FastAPI requires async exception handlers
    request: Request, _exc: Exception
) -> JSONResponse:
    """Handle unexpected exceptions."""
    request_id = getattr(request.state, "request_id", None)
    error_detail = ErrorDetail(
        message="Internal server error",
        type="InternalServerError",
        request_id=request_id,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_detail.model_dump(),
    )


async def validation_exception_handler(  # noqa: RUF029 - FastAPI requires async exception handlers
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    exc_str = f"{exc}".replace("\n", " ").replace("   ", " ")
    log.error(f"Validation error: {exc_str}")
    error_detail = ErrorDetail(
        message=exc_str,
        type="RequestValidationError",
        request_id=request_id,
    )
    return JSONResponse(
        content=error_detail.model_dump(),
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
