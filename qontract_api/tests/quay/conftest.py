from unittest.mock import MagicMock

import pytest
from qontract_utils.quay_api import QuayApi

from qontract_api.cache.base import CacheBackend
from qontract_api.config import Settings
from qontract_api.secret_manager import SecretManager


@pytest.fixture
def mock_quay_api() -> MagicMock:
    mock = MagicMock(spec=QuayApi)
    mock.org = "myorg"
    return mock


@pytest.fixture
def mock_cache() -> MagicMock:
    m = MagicMock(spec=CacheBackend)
    m.get_obj.return_value = None
    m.lock.return_value.__enter__ = MagicMock()
    m.lock.return_value.__exit__ = MagicMock(return_value=False)
    return m


@pytest.fixture
def mock_settings() -> Settings:
    return Settings()


@pytest.fixture
def mock_secret_manager() -> MagicMock:
    mock = MagicMock(spec=SecretManager)
    mock.read.return_value = "test-token"
    return mock
