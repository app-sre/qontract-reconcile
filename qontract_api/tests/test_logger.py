"""Tests for structured JSON logging."""

import json
import logging
from io import StringIO
from unittest.mock import patch

from qontract_api.logger import (
    CustomJsonFormatter,
    RequestIDFilter,
    get_logger,
    request_id_context,
    setup_logging,
)


def test_get_logger_returns_logger_instance() -> None:
    """Test that get_logger returns a logging.Logger instance."""
    logger = get_logger("test_module")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "test_module"


def test_request_id_filter_adds_request_id_from_context() -> None:
    """Test that RequestIDFilter adds request_id from context to log record."""
    # Set request_id in context
    token = request_id_context.set("test-request-id-123")

    try:
        # Create log record
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        # Apply filter
        filter_instance = RequestIDFilter()
        result = filter_instance.filter(record)

        # Assertions
        assert result is True  # Filter should always pass
        assert hasattr(record, "request_id")
        assert record.request_id == "test-request-id-123"
    finally:
        request_id_context.reset(token)


def test_request_id_filter_handles_missing_context() -> None:
    """Test that RequestIDFilter handles missing request_id gracefully."""
    # Don't set request_id in context (default is None)

    # Create log record
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None,
    )

    # Apply filter
    filter_instance = RequestIDFilter()
    result = filter_instance.filter(record)

    # Assertions
    assert result is True
    assert hasattr(record, "request_id")
    assert record.request_id is None


def test_custom_json_formatter_basic_fields() -> None:
    """Test that CustomJsonFormatter includes basic log fields in JSON output."""
    # Create formatter
    formatter = CustomJsonFormatter()

    # Create log record
    record = logging.LogRecord(
        name="test.module",
        level=logging.INFO,
        pathname="test.py",
        lineno=42,
        msg="Test message",
        args=(),
        exc_info=None,
    )

    # Format record
    output = formatter.format(record)
    log_dict = json.loads(output)

    # Assertions - basic fields
    assert "timestamp" in log_dict
    assert log_dict["level"] == "INFO"
    assert log_dict["logger"] == "test.module"
    assert log_dict["message"] == "Test message"


def test_custom_json_formatter_includes_request_id() -> None:
    """Test that CustomJsonFormatter includes request_id if present."""
    # Create formatter
    formatter = CustomJsonFormatter()

    # Create log record with request_id
    record = logging.LogRecord(
        name="test.module",
        level=logging.INFO,
        pathname="test.py",
        lineno=42,
        msg="Test message",
        args=(),
        exc_info=None,
    )
    record.request_id = "test-request-id-456"

    # Format record
    output = formatter.format(record)
    log_dict = json.loads(output)

    # Assertions
    assert log_dict["request_id"] == "test-request-id-456"


def test_custom_json_formatter_includes_extra_fields() -> None:
    """Test that CustomJsonFormatter includes extra fields from log calls."""
    # Create formatter
    formatter = CustomJsonFormatter()

    # Create log record
    record = logging.LogRecord(
        name="test.module",
        level=logging.INFO,
        pathname="test.py",
        lineno=42,
        msg="Test message",
        args=(),
        exc_info=None,
    )

    # Add extra fields (simulating logger.info(..., extra={...}))
    record.workspace = "test-workspace"
    record.usergroup = "test-usergroup"
    record.action_type = "update_users"
    record.user_count = 42

    # Format record
    output = formatter.format(record)
    log_dict = json.loads(output)

    # Assertions - extra fields should be included
    assert log_dict["workspace"] == "test-workspace"
    assert log_dict["usergroup"] == "test-usergroup"
    assert log_dict["action_type"] == "update_users"
    assert log_dict["user_count"] == 42


def test_custom_json_formatter_excludes_internal_fields() -> None:
    """Test that CustomJsonFormatter excludes internal logging fields."""
    # Create formatter
    formatter = CustomJsonFormatter()

    # Create log record
    record = logging.LogRecord(
        name="test.module",
        level=logging.INFO,
        pathname="/path/to/test.py",
        lineno=42,
        msg="Test message",
        args=(),
        exc_info=None,
    )

    # Format record
    output = formatter.format(record)
    log_dict = json.loads(output)

    # Assertions - internal fields should NOT be included
    excluded_fields = [
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
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "thread",
        "threadName",
    ]

    for field in excluded_fields:
        assert field not in log_dict


def test_custom_json_formatter_includes_exception_info() -> None:
    """Test that CustomJsonFormatter includes exception info when present."""
    import sys

    # Create formatter
    formatter = CustomJsonFormatter()

    # Create log record with exception
    try:
        raise ValueError("Test error")  # noqa: TRY301 - Test exception raising pattern
    except ValueError:
        # Get actual exception info tuple (not just True)
        exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="test.module",
            level=logging.ERROR,
            pathname="test.py",
            lineno=42,
            msg="Test error occurred",
            args=(),
            exc_info=exc_info,
        )

    # Format record
    output = formatter.format(record)
    log_dict = json.loads(output)

    # Assertions
    assert "exception" in log_dict
    assert "ValueError: Test error" in log_dict["exception"]
    assert "Traceback" in log_dict["exception"]


def test_logger_output_is_valid_json() -> None:
    """Test that actual logger output is valid JSON."""
    # Create logger with JSON formatter
    test_logger = logging.getLogger("test.json.output")
    test_logger.setLevel(logging.INFO)
    test_logger.handlers.clear()

    # Capture output
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    formatter = CustomJsonFormatter()
    handler.setFormatter(formatter)
    handler.addFilter(RequestIDFilter())
    test_logger.addHandler(handler)
    test_logger.propagate = False

    # Set request_id in context
    token = request_id_context.set("test-req-789")

    try:
        # Log with extra fields
        test_logger.info(
            "Test log message",
            extra={
                "workspace": "my-workspace",
                "usergroup": "my-usergroup",
                "count": 123,
            },
        )

        # Get output
        output = stream.getvalue().strip()

        # Parse JSON
        log_dict = json.loads(output)

        # Assertions
        assert log_dict["message"] == "Test log message"
        assert log_dict["level"] == "INFO"
        assert log_dict["request_id"] == "test-req-789"
        assert log_dict["workspace"] == "my-workspace"
        assert log_dict["usergroup"] == "my-usergroup"
        assert log_dict["count"] == 123

    finally:
        request_id_context.reset(token)
        test_logger.handlers.clear()


def test_logger_with_multiple_extra_fields() -> None:
    """Test logger with many extra fields (real-world scenario)."""
    # Create logger
    test_logger = logging.getLogger("test.multi.fields")
    test_logger.setLevel(logging.INFO)
    test_logger.handlers.clear()

    # Capture output
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    formatter = CustomJsonFormatter()
    handler.setFormatter(formatter)
    test_logger.addHandler(handler)
    test_logger.propagate = False

    # Log with many extra fields (like in service.py)
    test_logger.info(
        "User changes for workspace/usergroup: +5 -2",
        extra={
            "workspace": "test-workspace",
            "usergroup": "test-usergroup",
            "users_to_add": 5,
            "users_to_remove": 2,
            "action_type": "update_users",
            "dry_run": True,
            "total_actions": 10,
        },
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

    test_logger.handlers.clear()


def test_setup_logging_with_json_format() -> None:
    """Test setup_logging uses JSON formatter when LOG_FORMAT_JSON=True."""
    with patch("qontract_api.logger.settings") as mock_settings:
        mock_settings.log_level = "INFO"
        mock_settings.log_format_json = True

        logger = setup_logging()

        assert logger.name == "qontract_api"
        # Handlers are on root logger for submodule support
        root_logger = logging.getLogger()
        assert len(root_logger.handlers) == 1
        handler = root_logger.handlers[0]
        assert isinstance(handler.formatter, CustomJsonFormatter)


def test_setup_logging_with_standard_format() -> None:
    """Test setup_logging uses standard formatter when LOG_FORMAT_JSON=False."""
    with patch("qontract_api.logger.settings") as mock_settings:
        mock_settings.log_level = "INFO"
        mock_settings.log_format_json = False

        logger = setup_logging()

        assert logger.name == "qontract_api"
        # Handlers are on root logger for submodule support
        root_logger = logging.getLogger()
        assert len(root_logger.handlers) == 1
        handler = root_logger.handlers[0]
        assert isinstance(handler.formatter, logging.Formatter)
        assert not isinstance(handler.formatter, CustomJsonFormatter)


def test_standard_formatter_output() -> None:
    """Test that standard formatter produces human-readable output."""
    test_logger = logging.getLogger("test.standard.format")
    test_logger.setLevel(logging.INFO)
    test_logger.handlers.clear()

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    test_logger.addHandler(handler)
    test_logger.propagate = False

    test_logger.info("Test message")

    output = stream.getvalue().strip()

    # Should NOT be JSON
    try:
        json.loads(output)
        assert False, "Output should not be valid JSON"  # noqa: B011, PT015
    except json.JSONDecodeError:
        pass  # Expected

    # Should contain human-readable components
    assert "test.standard.format" in output
    assert "INFO" in output
    assert "Test message" in output
    assert " - " in output  # Separator from format string

    test_logger.handlers.clear()
