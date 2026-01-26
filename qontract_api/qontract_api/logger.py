"""Logging configuration for qontract-api.

Supports two logging formats:
- JSON logging (production): Structured logs for log aggregation systems
- Standard logging (development): Human-readable logs with stacktraces

Configure via LOG_FORMAT_JSON environment variable (default: True).
"""

import logging

import structlog

from qontract_api.config import settings


def setup_logger(logger: str, log_level: str | None = None) -> logging.Logger:
    """Setup a specific logger with JSON formatting and request ID filter."""
    return structlog.get_logger(
        logger,
        wrapper_class=structlog.make_filtering_bound_logger(
            log_level or settings.log_level
        ),
    )


def setup_logging() -> structlog.typing.WrappedLogger:
    """Configure and return application logger.

    Uses JSON formatting by default (LOG_FORMAT_JSON=True).
    For development, set LOG_FORMAT_JSON=False for human-readable logs with stacktraces.

    Also configures the root logger to enable DEBUG logs from all submodules
    (qontract_utils, slack_sdk, etc.) when LOG_LEVEL=DEBUG.

    Supports excluding specific loggers from logging via LOG_EXCLUDE_LOGGERS
    (comma-separated list, e.g., "slack_sdk,urllib3").

    Returns:
        Configured root logger for qontract_api
    """
    # Configure root logger to capture logs from all submodules
    structlog.configure(
        processors=[
            # Prepare event dict for `ProcessorFormatter`.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )

    processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
    ]
    if settings.log_format_json:
        processors += [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(sort_keys=True),
        ]
    else:
        processors += [
            structlog.dev.ConsoleRenderer(),
        ]

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            *processors,
        ],
    )
    handler = logging.StreamHandler()
    # Use OUR `ProcessorFormatter` to format all `logging` entries.
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level)

    # Set WARNING level for excluded loggers to suppress DEBUG/INFO logs
    excluded_loggers = [
        name.strip()
        for name in [
            *settings.log_exclude_loggers.split(","),
            # exclude celery in api logs
            "celery",
            "celery.app.trace",
        ]
        if name.strip()
    ]
    for logger_name in excluded_loggers:
        excluded_logger = logging.getLogger(logger_name)
        excluded_logger.setLevel(logging.WARNING)

    return structlog.get_logger("qontract_api")


def get_logger(name: str) -> structlog.typing.WrappedLogger:
    """Get a logger instance for a specific module.

    All loggers inherit the JSON formatting configuration from the root logger.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Configured logger instance
    """
    return structlog.get_logger(name)
