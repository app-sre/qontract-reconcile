"""Tests for event formatters."""

from qontract_utils.events._models import Event

from qontract_api.subscriber._formatters import (
    GenericEventFormatter,
    format_event,
    register_formatter,
)


def test_generic_formatter_basic_event() -> None:
    """Test GenericEventFormatter with a basic event."""
    formatter = GenericEventFormatter()
    event = Event(
        source="test-source",
        type="test.created",
        data={"key": "value"},
    )

    output = formatter.format(event)

    # Should contain emoji (create emoji in this case), event type in backticks, source, and JSON data in code block
    assert output.startswith("🟢")  # create emoji since "create" is in the type
    assert "`test.created`" in output
    assert "test-source" in output
    assert "```" in output
    assert '"key": "value"' in output


def test_generic_formatter_error_event() -> None:
    """Test GenericEventFormatter with error event type."""
    formatter = GenericEventFormatter()
    event = Event(
        source="error-source",
        type="deploy.error",
        data={"message": "deployment failed"},
    )

    output = formatter.format(event)

    # Should start with error emoji
    assert output.startswith("🔴")


def test_generic_formatter_create_event() -> None:
    """Test GenericEventFormatter with create event type."""
    formatter = GenericEventFormatter()
    event = Event(
        source="resource-source",
        type="resource.create",
        data={"resource": "new"},
    )

    output = formatter.format(event)

    # Should start with create emoji
    assert output.startswith("🟢")


def test_generic_formatter_update_event() -> None:
    """Test GenericEventFormatter with update event type."""
    formatter = GenericEventFormatter()
    event = Event(
        source="config-source",
        type="config.update",
        data={"setting": "changed"},
    )

    output = formatter.format(event)

    # Should start with update emoji
    assert output.startswith("🔄")


def test_generic_formatter_delete_event() -> None:
    """Test GenericEventFormatter with delete event type."""
    formatter = GenericEventFormatter()
    event = Event(
        source="resource-source",
        type="resource.delete",
        data={"resource": "removed"},
    )

    output = formatter.format(event)

    # Should start with delete emoji
    assert output.startswith("🗑️")


def test_generic_formatter_unknown_event() -> None:
    """Test GenericEventFormatter with unknown event type."""
    formatter = GenericEventFormatter()
    event = Event(
        source="unknown-source",
        type="something.happened",
        data={"info": "details"},
    )

    output = formatter.format(event)

    # Should start with default emoji
    assert output.startswith("📢")


def test_format_event_uses_default_formatter() -> None:
    """Test format_event uses default formatter when no custom formatter registered."""
    event = Event(
        source="test-source",
        type="test.event",
        data={"test": "data"},
    )

    output = format_event(event)

    # Should use GenericEventFormatter
    assert "`test.event`" in output
    assert "test-source" in output
    assert '"test": "data"' in output


def test_register_formatter_overrides_default() -> None:
    """Test register_formatter allows custom formatter for specific type."""

    # Create a custom formatter
    class CustomFormatter:
        def format(self, event: Event) -> str:
            return f"CUSTOM: {event.type}"

    custom_formatter = CustomFormatter()
    register_formatter("custom.type", custom_formatter)

    event = Event(
        source="custom-source",
        type="custom.type",
        data={"custom": "data"},
    )

    output = format_event(event)

    # Should use custom formatter
    assert output == "CUSTOM: custom.type"


def test_generic_formatter_complex_data() -> None:
    """Test GenericEventFormatter with complex nested data."""
    formatter = GenericEventFormatter()
    event = Event(
        source="complex-source",
        type="complex.event",
        data={
            "nested": {
                "level1": {
                    "level2": "value",
                },
            },
            "list": [1, 2, 3],
            "mixed": [{"a": 1}, {"b": 2}],
        },
    )

    output = formatter.format(event)

    # Should properly format nested JSON
    assert '"nested"' in output
    assert '"level1"' in output
    assert '"level2": "value"' in output
    assert '"list": [' in output
    assert "1," in output or "1\n" in output  # JSON formatting varies
    assert "```" in output  # code block
