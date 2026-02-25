"""Shared pytest fixtures for subscriber tests."""

import pytest
from qontract_utils.events import Event


@pytest.fixture
def sample_event() -> Event:
    """Create a basic test event."""
    return Event(
        source="test-source",
        type="test.created",
        data={"key": "value"},
    )


@pytest.fixture
def error_event() -> Event:
    """Create an error test event."""
    return Event(
        source="deploy-service",
        type="deploy.error",
        data={"error": "timeout"},
    )
