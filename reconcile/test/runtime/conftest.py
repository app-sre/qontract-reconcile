import pytest

from reconcile.test.runtime.fixtures import (
    ShardableTestIntegration,
    ShardableTestIntegrationParams,
    SimpleTestIntegration,
    SimpleTestIntegrationParams,
)


@pytest.fixture
def shardable_test_integration() -> ShardableTestIntegration:
    return ShardableTestIntegration(params=ShardableTestIntegrationParams())


@pytest.fixture
def simple_test_integration() -> SimpleTestIntegration:
    return SimpleTestIntegration(params=SimpleTestIntegrationParams(int_arg=1))
