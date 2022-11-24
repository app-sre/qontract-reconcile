import time

import httpretty as _httpretty
import pytest

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret


@pytest.fixture
def patch_sleep(mocker):
    yield mocker.patch.object(time, "sleep")


@pytest.fixture()
def httpretty():
    with _httpretty.enabled(allow_net_connect=False):
        _httpretty.reset()
        yield _httpretty


@pytest.fixture
def secret_reader(mocker) -> None:
    mock_secretreader = mocker.patch(
        "reconcile.utils.secret_reader.SecretReader", autospec=True
    )
    mock_secretreader.read.return_value = "secret"
    mock_secretreader.read_secret.return_value = "secret"
    return mock_secretreader


@pytest.fixture
def vault_secret():
    return VaultSecret(
        path="path/test",
        field="key",
        format=None,
        version=None,
    )
