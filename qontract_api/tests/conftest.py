"""Pytest configuration and fixtures."""

import os
from collections.abc import Generator
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient


def pytest_configure() -> None:
    """Configure pytest environment before test collection.

    This hook runs before pytest starts collecting tests, ensuring
    environment variables are set before Settings() is instantiated
    at module import time.
    """
    # Set minimal required settings for tests
    os.environ.setdefault(
        "QAPI_SECRETS__DEFAULT_PROVIDER_URL", "https://vault.example.org"
    )
    os.environ.setdefault(
        "QAPI_SECRETS__PROVIDERS", '[{"url": "https://vault.example.org"}]'
    )


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Create test client WITHOUT cache initialization.

    This fixture does not initialize cache, useful for testing error scenarios.
    Use client_with_cache for tests that need a working cache.
    """
    from qontract_api.main import app

    # Ensure no cache is set
    if hasattr(app.state, "cache"):
        delattr(app.state, "cache")

    # raise_server_exceptions=False allows testing error responses (401, 404, etc.)
    # instead of raising exceptions in tests
    yield TestClient(app, raise_server_exceptions=False)

    # Cleanup
    if hasattr(app.state, "cache"):
        delattr(app.state, "cache")


@pytest.fixture
def client_with_cache() -> Generator[TestClient, None, None]:
    """Create test client with mocked cache in app.state.

    This fixture sets up a mock cache backend for tests that require cache.
    """
    from qontract_api.main import app

    # Mock cache backend
    mock_cache = Mock()
    mock_cache.ping.return_value = True
    mock_cache.get.return_value = None
    app.state.cache = mock_cache

    # raise_server_exceptions=False allows testing error responses (401, 404, etc.)
    # instead of raising exceptions in tests
    yield TestClient(app, raise_server_exceptions=False)

    # Cleanup
    if hasattr(app.state, "cache"):
        delattr(app.state, "cache")


@pytest.fixture
def mock_cache() -> Generator[Mock, None, None]:
    """Mock cache backend for testing (sync).

    Returns the mock object so tests can configure it.
    """
    from qontract_api.main import app

    mock = Mock()
    mock.ping.return_value = True
    mock.get.return_value = None
    app.state.cache = mock

    yield mock

    # Cleanup
    if hasattr(app.state, "cache"):
        delattr(app.state, "cache")
