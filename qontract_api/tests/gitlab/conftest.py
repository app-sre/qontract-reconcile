from unittest.mock import MagicMock

import pytest
from qontract_utils.gitlab_api import GitlabApi

from qontract_api.cache.base import CacheBackend
from qontract_api.config import Settings
from qontract_api.secret_manager import SecretManager


@pytest.fixture
def mock_gitlab_api() -> MagicMock:
    return MagicMock(spec=GitlabApi)


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
