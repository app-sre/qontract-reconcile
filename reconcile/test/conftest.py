import time
import httpretty as _httpretty

import pytest


@pytest.fixture
def patch_sleep(mocker):
    yield mocker.patch.object(time, "sleep")


@pytest.fixture()
def httpretty():
    with _httpretty.enabled(allow_net_connect=False):
        _httpretty.reset()
        yield _httpretty
