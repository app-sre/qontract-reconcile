"""Tests for subscriber handler."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qontract_utils.events import Event

from qontract_api.subscriber._subscriptions import event_handler


@pytest.mark.asyncio
@patch("qontract_api.subscriber._subscriptions.post_to_slack", new_callable=AsyncMock)
@patch("qontract_api.subscriber._subscriptions.format_event", return_value="formatted")
async def test_event_handler_processes_event(
    mock_format: MagicMock,
    mock_post: AsyncMock,
    sample_event: Event,
) -> None:
    """Test event_handler formats and posts events successfully."""
    await event_handler(sample_event)

    mock_format.assert_called_once_with(sample_event)
    mock_post.assert_called_once_with("formatted")


@pytest.mark.asyncio
@patch("qontract_api.subscriber._subscriptions.post_to_slack", new_callable=AsyncMock)
@patch("qontract_api.subscriber._subscriptions.format_event", return_value="formatted")
async def test_event_handler_isolates_errors(
    mock_format: MagicMock,
    mock_post: AsyncMock,
    sample_event: Event,
) -> None:
    """Test event_handler catches exceptions and doesn't re-raise (SUB-02)."""
    # Configure post_to_slack to raise an exception
    mock_post.side_effect = Exception("API error")

    # Should NOT raise — per-event error isolation
    await event_handler(sample_event)

    # Verify format and post were called despite error
    mock_format.assert_called_once_with(sample_event)
    mock_post.assert_called_once_with("formatted")


@pytest.mark.asyncio
@patch("qontract_api.subscriber._subscriptions.post_to_slack", new_callable=AsyncMock)
@patch("qontract_api.subscriber._subscriptions.format_event", return_value="formatted")
@patch("qontract_api.subscriber._subscriptions.events_received")
async def test_event_handler_increments_received_metric(
    mock_received: MagicMock,
    mock_format: MagicMock,
    mock_post: AsyncMock,
    sample_event: Event,
) -> None:
    """Test event_handler increments received counter."""
    await event_handler(sample_event)

    # Verify counter was incremented with event type label
    mock_received.labels.assert_called_once_with(event_type=sample_event.type)
    mock_received.labels.return_value.inc.assert_called_once()


@pytest.mark.asyncio
@patch("qontract_api.subscriber._subscriptions.post_to_slack", new_callable=AsyncMock)
@patch("qontract_api.subscriber._subscriptions.format_event", return_value="formatted")
@patch("qontract_api.subscriber._subscriptions.events_posted")
async def test_event_handler_increments_posted_metric_on_success(
    mock_posted: MagicMock,
    mock_format: MagicMock,
    mock_post: AsyncMock,
    sample_event: Event,
) -> None:
    """Test event_handler increments posted counter on success."""
    await event_handler(sample_event)

    # Verify counter was incremented with event type label
    mock_posted.labels.assert_called_once_with(event_type=sample_event.type)
    mock_posted.labels.return_value.inc.assert_called_once()


@pytest.mark.asyncio
@patch("qontract_api.subscriber._subscriptions.post_to_slack", new_callable=AsyncMock)
@patch("qontract_api.subscriber._subscriptions.format_event", return_value="formatted")
@patch("qontract_api.subscriber._subscriptions.events_failed")
async def test_event_handler_increments_failed_metric_on_error(
    mock_failed: MagicMock,
    mock_format: MagicMock,
    mock_post: AsyncMock,
    sample_event: Event,
) -> None:
    """Test event_handler increments failed counter on error."""
    # Configure post_to_slack to raise an exception
    mock_post.side_effect = ValueError("Test error")

    await event_handler(sample_event)

    # Verify counter was incremented with event type and error type labels
    mock_failed.labels.assert_called_once_with(
        event_type=sample_event.type,
        error_type="ValueError",
    )
    mock_failed.labels.return_value.inc.assert_called_once()


@pytest.mark.asyncio
@patch("qontract_api.subscriber._subscriptions.post_to_slack", new_callable=AsyncMock)
@patch("qontract_api.subscriber._subscriptions.format_event", return_value="formatted")
@patch("qontract_api.subscriber._subscriptions.event_processing_duration")
async def test_event_handler_records_duration(
    mock_duration: MagicMock,
    mock_format: MagicMock,
    mock_post: AsyncMock,
    sample_event: Event,
) -> None:
    """Test event_handler records processing duration."""
    await event_handler(sample_event)

    # Verify histogram was observed with event type label
    mock_duration.labels.assert_called_once_with(event_type=sample_event.type)
    mock_duration.labels.return_value.observe.assert_called_once()
    # Verify observed duration is a positive float
    call_args = mock_duration.labels.return_value.observe.call_args[0]
    assert isinstance(call_args[0], float)
    assert call_args[0] >= 0


@pytest.mark.asyncio
@patch("qontract_api.subscriber._subscriptions.post_to_slack", new_callable=AsyncMock)
@patch("qontract_api.subscriber._subscriptions.format_event")
async def test_event_handler_format_exception_isolated(
    mock_format: MagicMock,
    mock_post: AsyncMock,
    sample_event: Event,
) -> None:
    """Test event_handler handles format_event exceptions."""
    # Configure format_event to raise an exception
    mock_format.side_effect = KeyError("Missing field")

    # Should NOT raise — per-event error isolation
    await event_handler(sample_event)

    # Verify format was called but post was not
    mock_format.assert_called_once_with(sample_event)
    mock_post.assert_not_called()
