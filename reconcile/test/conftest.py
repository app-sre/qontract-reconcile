import time

import pytest


@pytest.fixture
def patch_sleep(mocker):
    yield mocker.patch.object(time, "sleep")
