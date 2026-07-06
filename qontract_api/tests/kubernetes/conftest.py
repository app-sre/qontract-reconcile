"""Shared fixtures for Kubernetes workspace client tests."""

from unittest.mock import MagicMock

import pytest

from qontract_api.cache.base import CacheBackend
from qontract_api.config import Settings


@pytest.fixture
def mock_kubernetes_api() -> MagicMock:
    """Mock Layer 1 KubernetesApi client."""
    return MagicMock()


@pytest.fixture
def mock_cache() -> MagicMock:
    """Mock CacheBackend with double-check locking support."""
    m = MagicMock(spec=CacheBackend)
    m.get_obj.return_value = None
    m.lock.return_value.__enter__ = MagicMock()
    m.lock.return_value.__exit__ = MagicMock(return_value=False)
    return m


@pytest.fixture
def mock_settings() -> Settings:
    return Settings()
