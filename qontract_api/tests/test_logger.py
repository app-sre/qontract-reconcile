"""Tests for structured logging with structlog."""

import json
import logging
from io import StringIO
from unittest.mock import patch

import pytest
import structlog
from structlog.typing import Processor

from qontract_api.logger import get_logger, setup_logging


def test_get_logger_returns_structlog_instance() -> None:
    """Test that get_logger returns a structlog logger instance."""
    logger = get_logger("test_module")
    # structlog returns a BoundLoggerLazyProxy
    assert hasattr(logger, "info")
    assert hasattr(logger, "debug")
    assert hasattr(logger, "error")


def test_setup_logging_returns_qontract_api_logger() -> None:
    """Test that setup_logging returns configured qontract_api logger."""
    with patch("qontract_api.logger.settings") as mock_settings:
        mock_settings.log_level = "INFO"
        mock_settings.log_format_json = True
        mock_settings.log_exclude_loggers = ""
        mock_settings.sentry_dsn = ""

        logger = setup_logging()

        # Verify it's a structlog logger with expected methods
        assert hasattr(logger, "info")
        assert hasattr(logger, "debug")
        assert hasattr(logger, "error")


def test_setup_logging_with_json_format() -> None:
    """Test setup_logging uses JSON formatter when LOG_FORMAT_JSON=True."""
    with patch("qontract_api.logger.settings") as mock_settings:
        mock_settings.log_level = "INFO"
        mock_settings.log_format_json = True
        mock_settings.log_exclude_loggers = ""
        mock_settings.sentry_dsn = ""

        # Clear existing handlers
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        logger = setup_logging()

        # Verify logger instance has expected methods
        assert hasattr(logger, "info")

        # Verify root logger has handler
        assert len(root_logger.handlers) >= 1


def test_setup_logging_with_standard_format() -> None:
    """Test setup_logging uses console formatter when LOG_FORMAT_JSON=False."""
    with patch("qontract_api.logger.settings") as mock_settings:
        mock_settings.log_level = "INFO"
        mock_settings.log_format_json = False
        mock_settings.log_exclude_loggers = ""
        mock_settings.sentry_dsn = ""

        # Clear existing handlers
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        logger = setup_logging()

        # Verify logger instance has expected methods
        assert hasattr(logger, "info")

        # Verify root logger has handler
        assert len(root_logger.handlers) >= 1


def test_logger_with_json_output() -> None:
    """Test that logger produces valid JSON output when configured."""
    with patch("qontract_api.logger.settings") as mock_settings:
        mock_settings.log_level = "INFO"
        mock_settings.log_format_json = True
        mock_settings.log_exclude_loggers = ""
        mock_settings.sentry_dsn = ""

        # Setup logging with JSON format
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        # Capture output
        stream = StringIO()
        handler = logging.StreamHandler(stream)

        processors: list[Processor] = [
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(sort_keys=True),
        ]

        formatter = structlog.stdlib.ProcessorFormatter(
            processors=processors,
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)

        # Configure structlog
        structlog.configure(
            processors=[
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
        )

        # Get logger and log message
        test_logger = structlog.get_logger("test.json.output")
        test_logger.info("Test log message", workspace="my-workspace", count=123)

        # Get output
        output = stream.getvalue().strip()

        # Parse JSON
        log_dict = json.loads(output)

        # Assertions
        assert log_dict["event"] == "Test log message"
        assert log_dict["level"] == "info"
        assert log_dict["workspace"] == "my-workspace"
        assert log_dict["count"] == 123

        root_logger.handlers.clear()


def test_logger_with_context_vars() -> None:
    """Test that logger includes context variables in output."""
    with patch("qontract_api.logger.settings") as mock_settings:
        mock_settings.log_level = "INFO"
        mock_settings.log_format_json = True
        mock_settings.log_exclude_loggers = ""
        mock_settings.sentry_dsn = ""

        # Setup logging with JSON format
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        # Capture output
        stream = StringIO()
        handler = logging.StreamHandler(stream)

        processors: list[Processor] = [
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
            structlog.processors.JSONRenderer(sort_keys=True),
        ]

        formatter = structlog.stdlib.ProcessorFormatter(
            processors=processors,
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)

        # Configure structlog
        structlog.configure(
            processors=[
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
        )

        # Set context vars
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id="test-req-123")

        # Get logger and log message
        test_logger = structlog.get_logger("test.context")
        test_logger.info("Test message")

        # Get output
        output = stream.getvalue().strip()

        # Parse JSON
        log_dict = json.loads(output)

        # Assertions
        assert log_dict["request_id"] == "test-req-123"

        structlog.contextvars.clear_contextvars()
        root_logger.handlers.clear()


def test_logger_with_extra_fields() -> None:
    """Test logger with many extra fields (real-world scenario)."""
    with patch("qontract_api.logger.settings") as mock_settings:
        mock_settings.log_level = "INFO"
        mock_settings.log_format_json = True
        mock_settings.log_exclude_loggers = ""
        mock_settings.sentry_dsn = ""

        # Setup logging
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        # Capture output
        stream = StringIO()
        handler = logging.StreamHandler(stream)

        processors: list[Processor] = [
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
            structlog.processors.JSONRenderer(sort_keys=True),
        ]

        formatter = structlog.stdlib.ProcessorFormatter(
            processors=processors,
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)

        # Configure structlog
        structlog.configure(
            processors=[
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
        )

        # Get logger and log with many fields
        test_logger = structlog.get_logger("test.multi.fields")
        test_logger.info(
            "User changes for workspace/usergroup: +5 -2",
            workspace="test-workspace",
            usergroup="test-usergroup",
            users_to_add=5,
            users_to_remove=2,
            action_type="update_users",
            dry_run=True,
            total_actions=10,
        )

        # Get output
        output = stream.getvalue().strip()
        log_dict = json.loads(output)

        # Assertions - all extra fields present
        assert log_dict["workspace"] == "test-workspace"
        assert log_dict["usergroup"] == "test-usergroup"
        assert log_dict["users_to_add"] == 5
        assert log_dict["users_to_remove"] == 2
        assert log_dict["action_type"] == "update_users"
        assert log_dict["dry_run"] is True
        assert log_dict["total_actions"] == 10

        root_logger.handlers.clear()


def test_logger_with_exception() -> None:
    """Test that logger includes exception info when present."""
    with patch("qontract_api.logger.settings") as mock_settings:
        mock_settings.log_level = "INFO"
        mock_settings.log_format_json = True
        mock_settings.log_exclude_loggers = ""
        mock_settings.sentry_dsn = ""

        # Setup logging
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        # Capture output
        stream = StringIO()
        handler = logging.StreamHandler(stream)

        processors: list[Processor] = [
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(sort_keys=True),
        ]

        formatter = structlog.stdlib.ProcessorFormatter(
            processors=processors,
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)

        # Configure structlog
        structlog.configure(
            processors=[
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
        )

        # Get logger and log exception
        test_logger = structlog.get_logger("test.exception")

        try:
            raise ValueError("Test error")  # noqa: TRY301
        except ValueError:
            test_logger.exception("Test error occurred")

        # Get output
        output = stream.getvalue().strip()
        log_dict = json.loads(output)

        # Assertions
        assert "exception" in log_dict
        assert isinstance(log_dict["exception"], list)
        assert len(log_dict["exception"]) > 0
        # Check exception structure
        exc_info = log_dict["exception"][0]
        assert exc_info["exc_type"] == "ValueError"
        assert exc_info["exc_value"] == "Test error"

        root_logger.handlers.clear()


def test_sentry_init_called_when_dsn_provided() -> None:
    """Test that sentry_sdk.init is called when SENTRY_DSN is provided."""
    with (
        patch("qontract_api.logger.settings") as mock_settings,
        patch("qontract_api.logger.sentry_sdk.init") as mock_sentry_init,
    ):
        mock_settings.log_level = "INFO"
        mock_settings.log_format_json = True
        mock_settings.log_exclude_loggers = ""
        mock_settings.sentry_dsn = "https://example@sentry.io/123"
        mock_settings.sentry_event_level = "ERROR"

        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        setup_logging()

        mock_sentry_init.assert_called_once()
        call_args = mock_sentry_init.call_args

        assert call_args.kwargs["dsn"] == "https://example@sentry.io/123"
        assert call_args.kwargs["send_default_pii"] is True
        assert call_args.kwargs["enable_logs"] is True
        assert call_args.kwargs["ignore_errors"] == [ConnectionError]

        root_logger.handlers.clear()


def test_sentry_init_not_called_when_dsn_empty() -> None:
    """Test that sentry_sdk.init is not called when SENTRY_DSN is empty."""
    with (
        patch("qontract_api.logger.settings") as mock_settings,
        patch("qontract_api.logger.sentry_sdk.init") as mock_sentry_init,
    ):
        mock_settings.log_level = "INFO"
        mock_settings.log_format_json = True
        mock_settings.log_exclude_loggers = ""
        mock_settings.sentry_dsn = ""

        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        setup_logging()

        mock_sentry_init.assert_not_called()

        root_logger.handlers.clear()


def test_sentry_init_with_error_level() -> None:
    """Test sentry_sdk.init uses ERROR event level correctly."""
    with (
        patch("qontract_api.logger.settings") as mock_settings,
        patch("qontract_api.logger.sentry_sdk.init") as mock_sentry_init,
        patch("qontract_api.logger.LoggingIntegration") as mock_logging_integration,
    ):
        mock_settings.log_level = "INFO"
        mock_settings.log_format_json = True
        mock_settings.log_exclude_loggers = ""
        mock_settings.sentry_dsn = "https://example@sentry.io/123"
        mock_settings.sentry_event_level = "ERROR"

        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        setup_logging()

        mock_sentry_init.assert_called_once()
        mock_logging_integration.assert_called_once_with(event_level=logging.ERROR)

        root_logger.handlers.clear()


def test_sentry_init_with_critical_level() -> None:
    """Test sentry_sdk.init uses CRITICAL event level correctly."""
    with (
        patch("qontract_api.logger.settings") as mock_settings,
        patch("qontract_api.logger.sentry_sdk.init") as mock_sentry_init,
        patch("qontract_api.logger.LoggingIntegration") as mock_logging_integration,
    ):
        mock_settings.log_level = "INFO"
        mock_settings.log_format_json = True
        mock_settings.log_exclude_loggers = ""
        mock_settings.sentry_dsn = "https://example@sentry.io/123"
        mock_settings.sentry_event_level = "CRITICAL"

        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        setup_logging()

        mock_sentry_init.assert_called_once()
        mock_logging_integration.assert_called_once_with(event_level=logging.CRITICAL)

        root_logger.handlers.clear()


def test_sentry_init_with_invalid_level_raises_error() -> None:
    """Test that invalid SENTRY_EVENT_LEVEL raises NotImplementedError."""
    with (
        patch("qontract_api.logger.settings") as mock_settings,
        patch("qontract_api.logger.sentry_sdk.init"),
    ):
        mock_settings.log_level = "INFO"
        mock_settings.log_format_json = True
        mock_settings.log_exclude_loggers = ""
        mock_settings.sentry_dsn = "https://example@sentry.io/123"
        mock_settings.sentry_event_level = "WARNING"

        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        with pytest.raises(
            NotImplementedError, match="Unsupported sentry_event_level: WARNING"
        ):
            setup_logging()

        root_logger.handlers.clear()
