from unittest.mock import create_autospec
import pytest

import reconcile.utils.secret_reader
from reconcile.utils import vault
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.utils.secret_reader import (
    ConfigSecretReader,
    SecretReader,
    SecretNotFound,
    VaultSecretReader,
)
from reconcile.utils.vault import _VaultClient


VAULT_READ_EXPECTED = {"key": "value"}
VAULT_READ_ALL_EXPECTED = {"key2": "value2"}


@pytest.fixture
def vault_mock():
    vault_mock = create_autospec(_VaultClient)
    vault_mock.read.side_effect = [VAULT_READ_EXPECTED] * 100
    vault_mock.read_all.side_effect = [VAULT_READ_ALL_EXPECTED] * 100
    return vault_mock


@pytest.fixture
def vault_secret():
    return VaultSecret(
        path="path/test",
        field="key",
        format=None,
        version=None,
    )


def to_dict(secret):
    return {
        "path": secret.path,
        "field": secret.field,
        "format": secret.q_format,
        "version": secret.version,
    }


def test_vault_secret_reader_typed_read(vault_mock, vault_secret):
    vault_secret_reader = VaultSecretReader(vault_client=vault_mock)
    result = vault_secret_reader.read_secret(vault_secret)

    assert result == VAULT_READ_EXPECTED
    vault_mock.read.assert_called_once_with(to_dict(vault_secret))
    vault_mock.read_all.assert_not_called()


def test_vault_secret_reader_typed_read_all(vault_mock, vault_secret):
    vault_secret_reader = VaultSecretReader(vault_client=vault_mock)
    result = vault_secret_reader.read_all_secret(vault_secret)

    assert result == VAULT_READ_ALL_EXPECTED
    vault_mock.read_all.assert_called_once_with(to_dict(vault_secret))
    vault_mock.read.assert_not_called()


def test_vault_secret_reader_parameters_read(vault_mock, vault_secret):
    vault_secret_reader = VaultSecretReader(vault_client=vault_mock)
    result = vault_secret_reader.read_with_parameters(
        path=vault_secret.path,
        field=vault_secret.field,
        format=vault_secret.q_format,
        version=vault_secret.version,
    )

    assert result == VAULT_READ_EXPECTED
    vault_mock.read.assert_called_once_with(to_dict(vault_secret))
    vault_mock.read_all.assert_not_called()


def test_vault_secret_reader_parameters_read_all(vault_mock, vault_secret):
    vault_secret_reader = VaultSecretReader(vault_client=vault_mock)
    result = vault_secret_reader.read_all_with_parameters(
        path=vault_secret.path,
        field=vault_secret.field,
        format=vault_secret.q_format,
        version=vault_secret.version,
    )

    assert result == VAULT_READ_ALL_EXPECTED
    vault_mock.read_all.assert_called_once_with(to_dict(vault_secret))
    vault_mock.read.assert_not_called()


def test_vault_secret_reader_raises(vault_mock, vault_secret, patch_sleep):
    vault_mock.read.side_effect = [vault.SecretNotFound] * 100
    vault_secret_reader = VaultSecretReader(vault_client=vault_mock)

    with pytest.raises(SecretNotFound):
        vault_secret_reader.read_secret(vault_secret)

    vault_mock.read.assert_called_with(to_dict(vault_secret))
    vault_mock.read_all.assert_not_called()


def test_config_secret_reader_raises(vault_secret, patch_sleep):
    config_secret_reader = ConfigSecretReader()

    with pytest.raises(SecretNotFound):
        config_secret_reader.read_secret(vault_secret)


def test_read_vault_raises(mocker, patch_sleep):
    """
    Ensure that secret_reader.SecretNotFound is raised instead of
    vault.SecretNotFound.
    """
    mock_vault_client = mocker.patch.object(
        reconcile.utils.secret_reader, "VaultClient", autospec=_VaultClient
    )
    settings = {"vault": True}
    mock_vault_client.return_value.read.side_effect = vault.SecretNotFound

    secret_reader = SecretReader(settings=settings)

    with pytest.raises(SecretNotFound):
        secret_reader.read({"path": "test", "field": "some-field"})


def test_read_config_raises(mocker, patch_sleep):
    """
    Ensure that secret_reader.SecretNotFound is raised instead of
    config.SecretNotFound.
    """
    mocker.patch.object(
        reconcile.utils.secret_reader, "VaultClient", autospec=_VaultClient
    )

    secret_reader = SecretReader()

    with pytest.raises(SecretNotFound):
        secret_reader.read({"path": "test", "field": "some-field"})


def test_read_all_vault_raises(mocker, patch_sleep):
    """
    Ensure that secret_reader.SecretNotFound is raised instead of
    vault.SecretNotFound.
    """
    mock_vault_client = mocker.patch.object(
        reconcile.utils.secret_reader, "VaultClient", autospec=_VaultClient
    )

    settings = {"vault": True}
    mock_vault_client.return_value.read_all.side_effect = vault.SecretNotFound

    secret_reader = SecretReader(settings=settings)

    with pytest.raises(SecretNotFound):
        secret_reader.read_all({"path": "test", "field": "some-field"})


def test_read_all_config_raises(mocker, patch_sleep):
    """
    Ensure that secret_reader.SecretNotFound is raised instead of
    config.SecretNotFound.
    """
    mocker.patch.object(
        reconcile.utils.secret_reader, "VaultClient", autospec=_VaultClient
    )

    secret_reader = SecretReader()

    with pytest.raises(SecretNotFound):
        secret_reader.read_all({"path": "test", "field": "some-field"})
