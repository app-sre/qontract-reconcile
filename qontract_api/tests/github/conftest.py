from unittest.mock import MagicMock

import pytest
from qontract_utils.github_api.api import GithubApi

from qontract_api.cache.base import CacheBackend
from qontract_api.config import Settings


@pytest.fixture
def mock_github_api() -> MagicMock:
    m = MagicMock(spec=GithubApi)
    m.credential_id = "test-credential-id"
    return m


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
