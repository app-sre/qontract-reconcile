from unittest.mock import MagicMock, create_autospec

import pytest
from pytest_mock import MockerFixture

import reconcile.utils.secret_reader
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.utils import vault
from reconcile.utils.secret_reader import (
    ConfigSecretReader,
    SecretNotFoundError,
    SecretReader,
    VaultSecretReader,
)
from reconcile.utils.vault import VaultClient

VAULT_READ_EXPECTED = {"key": "value"}
VAULT_READ_ALL_EXPECTED = {"key2": "value2"}


@pytest.fixture
def vault_mock() -> MagicMock:
    vault_mock = create_autospec(VaultClient)
    vault_mock.read.side_effect = [VAULT_READ_EXPECTED] * 100
    vault_mock.read_all.side_effect = [VAULT_READ_ALL_EXPECTED] * 100
    return vault_mock


def test_vault_secret_reader_typed_read(
    vault_mock: MagicMock, vault_secret: VaultSecret
) -> None:
    vault_secret_reader = VaultSecretReader(vault_client=vault_mock)
    result = vault_secret_reader.read_secret(vault_secret)

    assert result == VAULT_READ_EXPECTED
    vault_mock.read.assert_called_once_with(SecretReader.to_dict(vault_secret))
    vault_mock.read_all.assert_not_called()


def test_vault_secret_reader_typed_read_all(
    vault_mock: MagicMock, vault_secret: VaultSecret
) -> None:
    vault_secret_reader = VaultSecretReader(vault_client=vault_mock)
    result = vault_secret_reader.read_all_secret(vault_secret)

    assert result == VAULT_READ_ALL_EXPECTED
    vault_mock.read_all.assert_called_once_with(SecretReader.to_dict(vault_secret))
    vault_mock.read.assert_not_called()


def test_vault_secret_reader_parameters_read(
    vault_mock: MagicMock, vault_secret: VaultSecret
) -> None:
    vault_secret_reader = VaultSecretReader(vault_client=vault_mock)
    result = vault_secret_reader.read_with_parameters(
        path=vault_secret.path,
        field=vault_secret.field,
        format=vault_secret.q_format,
        version=vault_secret.version,
    )

    assert result == VAULT_READ_EXPECTED
    vault_mock.read.assert_called_once_with(SecretReader.to_dict(vault_secret))
    vault_mock.read_all.assert_not_called()


def test_vault_secret_reader_parameters_read_all(
    vault_mock: MagicMock, vault_secret: VaultSecret
) -> None:
    vault_secret_reader = VaultSecretReader(vault_client=vault_mock)
    result = vault_secret_reader.read_all_with_parameters(
        path=vault_secret.path,
        field=vault_secret.field,
        format=vault_secret.q_format,
        version=vault_secret.version,
    )

    assert result == VAULT_READ_ALL_EXPECTED
    vault_mock.read_all.assert_called_once_with(SecretReader.to_dict(vault_secret))
    vault_mock.read.assert_not_called()


def test_vault_secret_reader_raises(
    vault_mock: MagicMock, vault_secret: VaultSecret, patch_sleep: MagicMock
) -> None:
    vault_mock.read.side_effect = [vault.SecretNotFoundError] * 100
    vault_secret_reader = VaultSecretReader(vault_client=vault_mock)

    with pytest.raises(SecretNotFoundError):
        vault_secret_reader.read_secret(vault_secret)

    vault_mock.read.assert_called_with(SecretReader.to_dict(vault_secret))
    vault_mock.read_all.assert_not_called()


def test_config_secret_reader_raises(
    vault_secret: MagicMock, patch_sleep: MagicMock
) -> None:
    config_secret_reader = ConfigSecretReader()

    with pytest.raises(SecretNotFoundError):
        config_secret_reader.read_secret(vault_secret)


def test_read_vault_raises(mocker: MockerFixture, patch_sleep: MagicMock) -> None:
    """
    Ensure that secret_reader.SecretNotFound is raised instead of
    vault.SecretNotFound.
    """
    mock_vault_client = create_autospec(VaultClient)
    mock_vault_client.read.side_effect = vault.SecretNotFoundError

    mocker.patch(
        "reconcile.utils.secret_reader.VaultClient.get_instance",
        return_value=mock_vault_client,
    )

    settings = {"vault": True}

    secret_reader = SecretReader(settings=settings)

    with pytest.raises(SecretNotFoundError):
        secret_reader.read({"path": "test", "field": "some-field"})


def test_read_config_raises(mocker: MockerFixture, patch_sleep: MagicMock) -> None:
    """
    Ensure that secret_reader.SecretNotFound is raised instead of
    config.SecretNotFound.
    """
    mocker.patch.object(
        reconcile.utils.secret_reader, "VaultClient", autospec=VaultClient
    )

    secret_reader = SecretReader()

    with pytest.raises(SecretNotFoundError):
        secret_reader.read({"path": "test", "field": "some-field"})


def test_read_all_vault_raises(mocker: MockerFixture, patch_sleep: MagicMock) -> None:
    """
    Ensure that secret_reader.SecretNotFound is raised instead of
    vault.SecretNotFound.
    """
    mock_vault_client = mocker.patch(
        "reconcile.utils.secret_reader.VaultClient.get_instance"
    )
    mock_vault_client.return_value.read_all.side_effect = vault.SecretNotFoundError

    settings = {"vault": True}

    secret_reader = SecretReader(settings=settings)

    with pytest.raises(SecretNotFoundError):
        secret_reader.read_all({"path": "test", "field": "some-field"})


def test_read_all_config_raises(mocker: MockerFixture, patch_sleep: MagicMock) -> None:
    """
    Ensure that secret_reader.SecretNotFound is raised instead of
    config.SecretNotFound.
    """
    mocker.patch.object(
        reconcile.utils.secret_reader, "VaultClient", autospec=VaultClient
    )

    secret_reader = SecretReader()

    with pytest.raises(SecretNotFoundError):
        secret_reader.read_all({"path": "test", "field": "some-field"})
