"""Pytest configuration and fixtures."""

# ruff: noqa: PLC0415 - Lazy imports in fixtures are intentional

from collections.abc import Generator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from qontract_api.dependencies import dependencies


@pytest.fixture
def client() -> TestClient:
    """Create test client without lifespan (no cache initialization)."""
    from qontract_api.main import app

    # raise_server_exceptions=False allows testing error responses (401, 404, etc.)
    # instead of raising exceptions in tests
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def mock_cache() -> Generator[None, None, None]:
    """Mock cache backend for testing."""
    mock = AsyncMock()
    mock.ping.return_value = True
    mock.get.return_value = None
    dependencies.cache = mock

    yield

    dependencies.cache = None
