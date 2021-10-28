from unittest.mock import patch

import pytest

import reconcile.utils.secret_reader
from reconcile.utils import vault
from reconcile.utils.secret_reader import SecretReader, SecretNotFound
from reconcile.utils.vault import _VaultClient


@patch.object(reconcile.utils.secret_reader, 'VaultClient',
              autospec=_VaultClient)
def test_read_vault_raises(mock_vault_client):
    """
    Ensure that secret_reader.SecretNotFound is raised instead of
    vault.SecretNotFound.
    """
    settings = {'vault': True}
    mock_vault_client.return_value.read.side_effect = vault.SecretNotFound

    secret_reader = SecretReader(settings=settings)

    with pytest.raises(SecretNotFound):
        secret_reader.read({'path': 'test', 'field': 'some-field'})


def test_read_config_raises():
    """
    Ensure that secret_reader.SecretNotFound is raised instead of
    config.SecretNotFound.
    """
    secret_reader = SecretReader()

    with pytest.raises(SecretNotFound):
        secret_reader.read({'path': 'test', 'field': 'some-field'})


@patch.object(reconcile.utils.secret_reader, 'VaultClient',
              autospec=_VaultClient)
def test_read_all_vault_raises(mock_vault_client):
    """
    Ensure that secret_reader.SecretNotFound is raised instead of
    vault.SecretNotFound.
    """
    settings = {'vault': True}
    mock_vault_client.return_value.read_all.side_effect = vault.SecretNotFound

    secret_reader = SecretReader(settings=settings)

    with pytest.raises(SecretNotFound):
        secret_reader.read_all({'path': 'test', 'field': 'some-field'})


def test_read_all_config_raises():
    """
    Ensure that secret_reader.SecretNotFound is raised instead of
    config.SecretNotFound.
    """
    secret_reader = SecretReader()

    with pytest.raises(SecretNotFound):
        secret_reader.read_all({'path': 'test', 'field': 'some-field'})
