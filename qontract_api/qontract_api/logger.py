"""Logging configuration for qontract-api.

Supports two logging formats:
- JSON logging (production): Structured logs for log aggregation systems
- Standard logging (development): Human-readable logs with stacktraces

Configure via LOG_FORMAT_JSON environment variable (default: True).

See ADR-009 (to be written) for rationale and design decisions.
"""

import logging
import sys
from contextvars import ContextVar

from pythonjsonlogger.json import JsonFormatter

from qontract_api.config import settings

# Context variable for request ID (set by RequestIDMiddleware)
request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIDFilter(logging.Filter):
    """Logging filter that adds request_id to all log records.

    Retrieves request_id from context variable set by RequestIDMiddleware.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: PLR6301 - Required instance method for logging.Filter
        """Add request_id to log record if available.

        Args:
            record: Log record to modify

        Returns:
            True (always pass through)
        """
        record.request_id = request_id_context.get()
        return True


class CustomJsonFormatter(JsonFormatter):
    """Custom JSON formatter with enhanced field mapping.

    Ensures consistent field names and includes all relevant context.
    """

    def add_fields(
        self,
        log_record: dict[str, object],
        record: logging.LogRecord,
        message_dict: dict[str, object],
    ) -> None:
        """Add fields to the JSON log record.

        Args:
            log_record: Dictionary to populate with log fields
            record: Original log record
            message_dict: Message dictionary from format
        """
        super().add_fields(log_record, record, message_dict)

        # Standard fields
        log_record["timestamp"] = self.formatTime(record, self.datefmt)
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        log_record["message"] = record.getMessage()

        # Add request_id if available
        if hasattr(record, "request_id") and record.request_id:
            log_record["request_id"] = record.request_id

        # Add exception info if present
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        # Include all extra fields from log calls
        # (workspace, usergroup, action_type, etc.)
        excluded_fields = {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "thread",
            "threadName",
            "exc_info",
            "exc_text",
            "stack_info",
            "request_id",
        }
        log_record.update({
            key: value
            for key, value in record.__dict__.items()
            if key not in excluded_fields and not key.startswith("_")
        })


def setup_logging() -> logging.Logger:
    """Configure and return application logger.

    Uses JSON formatting by default (LOG_FORMAT_JSON=True).
    For development, set LOG_FORMAT_JSON=False for human-readable logs with stacktraces.

    Also configures the root logger to enable DEBUG logs from all submodules
    (qontract_utils, slack_sdk, etc.) when LOG_LEVEL=DEBUG.

    Supports excluding specific loggers from DEBUG logging via LOG_EXCLUDE_LOGGERS
    (comma-separated list, e.g., "slack_sdk,urllib3").

    Returns:
        Configured root logger for qontract_api
    """
    # Configure root logger to capture logs from all submodules
    root_logger = logging.getLogger()
    root_logger.setLevel(settings.log_level)

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Console handler for root logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(settings.log_level)

    # Choose formatter based on config
    formatter: logging.Formatter
    if settings.log_format_json:
        # JSON formatter for production
        formatter = CustomJsonFormatter(
            "%(timestamp)s %(level)s %(logger)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    else:
        # Human-readable formatter for development
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler.setFormatter(formatter)

    # Add request ID filter (works for both JSON and standard logging)
    handler.addFilter(RequestIDFilter())

    root_logger.addHandler(handler)

    # Get application logger (inherits from root)
    logger = logging.getLogger("qontract_api")
    logger.setLevel(settings.log_level)

    # Set WARNING level for excluded loggers to suppress DEBUG/INFO logs
    if settings.log_exclude_loggers:
        excluded_loggers = [
            name.strip()
            for name in settings.log_exclude_loggers.split(",")
            if name.strip()
        ]
        for logger_name in excluded_loggers:
            excluded_logger = logging.getLogger(logger_name)
            excluded_logger.setLevel(logging.WARNING)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a specific module.

    All loggers inherit the JSON formatting configuration from the root logger.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


# Initialize logging on module import
logger = setup_logging()
