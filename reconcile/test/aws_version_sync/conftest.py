import pytest

from reconcile.test.fixtures import Fixtures


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("aws_version_sync")
