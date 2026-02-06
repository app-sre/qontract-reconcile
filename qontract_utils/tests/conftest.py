"""Global test configuration for qontract_utils tests."""

from collections.abc import Generator

import pytest
import stamina


@pytest.fixture(autouse=True, scope="session")
def deactivate_retries() -> None:
    """Disable stamina retries globally for all tests.

    Individual retry tests can re-enable with the enable_retry fixture.
    """
    stamina.set_active(False)


@pytest.fixture
def enable_retry() -> Generator[None, None, None]:
    """Enable stamina retry for specific tests.

    Use this fixture in tests that verify retry behavior.
    """
    stamina.set_active(True)
    stamina.set_testing(True, attempts=3)
    yield
    stamina.set_testing(False)
    stamina.set_active(False)
