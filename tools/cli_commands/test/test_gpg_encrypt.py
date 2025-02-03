import json
from unittest.mock import (
    MagicMock,
    mock_open,
    patch,
)

import pytest
from pytest_mock import MockerFixture

from reconcile.queries import UserFilter
from reconcile.utils.secret_reader import SecretReader
from tools.cli_commands.gpg_encrypt import (
    ArgumentException,
    GPGEncryptCommand,
    GPGEncryptCommandData,
    UserException,
)


@pytest.fixture
def secret_reader(mocker: MockerFixture) -> MagicMock:
    mock_secretreader = mocker.patch(
        "reconcile.utils.secret_reader.SecretReader", autospec=True
    )
    mock_secretreader.read.return_value = "secret"
    mock_secretreader.read_secret.return_value = "secret"
    return mock_secretreader


def craft_command(
    command_data: GPGEncryptCommandData, secret_reader: SecretReader
) -> GPGEncryptCommand:
    command = GPGEncryptCommand.create(
        command_data=command_data,
        secret_reader=secret_reader,
    )
    return command


@patch("reconcile.utils.gpg.gpg_encrypt")
@patch("reconcile.queries.get_users_by")
def test_gpg_encrypt_from_vault(
    get_users_by_mock: MagicMock,
    gpg_encrypt_mock: MagicMock,
    secret_reader: MagicMock,
) -> None:
    vault_secret_path = "app-sre/test"
    target_user = "testuser"
    gpg_key = "xyz"
    secret = {"x": "y"}
    user_query = {
        "org_username": target_user,
        "public_gpg_key": gpg_key,
    }
    command = craft_command(
        command_data=GPGEncryptCommandData(
            vault_secret_path=vault_secret_path,
            target_user=target_user,
        ),
        secret_reader=secret_reader,
    )
    get_users_by_mock.side_effect = [[user_query]]
    gpg_encrypt_mock.side_effect = ["encrypted_content"]

    command.execute()

    secret_reader.assert_called_once_with({"path": vault_secret_path})
    get_users_by_mock.assert_called_once_with(
        refs=False,
        filter=UserFilter(
            org_username=target_user,
        ),
    )
    gpg_encrypt_mock.assert_called_once_with(
        content=json.dumps(secret, sort_keys=True, indent=4),
        public_gpg_key=gpg_key,
    )


@patch("reconcile.utils.gpg.gpg_encrypt")
@patch("reconcile.queries.get_users_by")
def test_gpg_encrypt_from_vault_with_version(
    get_users_by_mock: MagicMock, gpg_encrypt_mock: MagicMock, secret_reader: MagicMock
) -> None:
    vault_secret_path = "app-sre/test"
    target_user = "testuser"
    gpg_key = "xyz"
    version = 4
    secret = {"x": "y"}
    user_query = {
        "org_username": target_user,
        "public_gpg_key": gpg_key,
    }
    command = craft_command(
        command_data=GPGEncryptCommandData(
            vault_secret_path=vault_secret_path,
            vault_secret_version=version,
            target_user=target_user,
        ),
        secret_reader=secret_reader,
    )
    get_users_by_mock.side_effect = [[user_query]]
    gpg_encrypt_mock.side_effect = ["encrypted_content"]

    command.execute()

    secret_reader.assert_called_once_with({
        "path": vault_secret_path,
        "version": str(version),
    })
    get_users_by_mock.assert_called_once_with(
        refs=False,
        filter=UserFilter(
            org_username=target_user,
        ),
    )
    gpg_encrypt_mock.assert_called_once_with(
        content=json.dumps(secret, sort_keys=True, indent=4),
        public_gpg_key=gpg_key,
    )


@patch("reconcile.queries.get_users_by")
@patch("reconcile.queries.get_clusters")
def test_gpg_encrypt_oc_bad_path(
    get_clusters_mock: MagicMock, get_users_by_mock: MagicMock, secret_reader: MagicMock
) -> None:
    target_user = "testuser"
    user_query = {
        "org_username": target_user,
        "public_gpg_key": "xyz",
    }
    command = craft_command(
        command_data=GPGEncryptCommandData(
            openshift_path="cluster/secret",
            target_user=target_user,
        ),
        secret_reader=secret_reader,
    )

    get_users_by_mock.side_effect = [[user_query]]
    get_clusters_mock.side_effect = [[{"name": "cluster"}]]

    with pytest.raises(ArgumentException) as exc:
        command.execute()
    assert "Wrong format!" in str(exc.value)


@patch("reconcile.queries.get_users_by")
@patch("reconcile.queries.get_clusters_by")
def test_gpg_encrypt_oc_cluster_not_exists(
    get_clusters_mock: MagicMock, get_users_by_mock: MagicMock, secret_reader: MagicMock
) -> None:
    target_user = "testuser"
    user_query = {
        "org_username": target_user,
        "public_gpg_key": "xyz",
    }
    command = craft_command(
        command_data=GPGEncryptCommandData(
            openshift_path="cluster/namespace/secret",
            target_user=target_user,
        ),
        secret_reader=secret_reader,
    )

    get_users_by_mock.side_effect = [[user_query]]
    get_clusters_mock.side_effect = [[]]

    with pytest.raises(ArgumentException) as exc:
        command.execute()
    assert "No cluster found" in str(exc.value)


@patch("builtins.open", new_callable=mock_open, read_data="test-data")
@patch("reconcile.utils.gpg.gpg_encrypt")
@patch("reconcile.queries.get_users_by")
def test_gpg_encrypt_from_local_file(
    get_users_by_mock: MagicMock,
    gpg_encrypt_mock: MagicMock,
    mock_file: MagicMock,
    capsys: pytest.CaptureFixture,
    secret_reader: MagicMock,
) -> None:
    target_user = "testuser"
    file_path = "/tmp/tmp"
    encrypted_content = "encrypted_content"
    user_query = {
        "org_username": target_user,
        "public_gpg_key": "xyz",
    }
    command = craft_command(
        command_data=GPGEncryptCommandData(
            secret_file_path=file_path,
            target_user=target_user,
        ),
        secret_reader=secret_reader,
    )
    get_users_by_mock.side_effect = [[user_query]]
    gpg_encrypt_mock.side_effect = [encrypted_content]

    command.execute()

    captured = capsys.readouterr()
    assert captured.out == f"{encrypted_content}\n"
    mock_file.assert_called_once_with(file_path, encoding="locale")
    secret_reader.read_all.assert_not_called()


@patch("reconcile.queries.get_users_by")
def test_gpg_encrypt_user_not_found(
    get_users_by_mock: MagicMock, secret_reader: MagicMock
) -> None:
    target_user = "testuser"
    command = craft_command(
        command_data=GPGEncryptCommandData(
            vault_secret_path="/tmp/tmp",
            target_user=target_user,
        ),
        secret_reader=secret_reader,
    )
    get_users_by_mock.side_effect = [[]]

    with pytest.raises(UserException) as exc:
        command.execute()
    assert "Expected to find exactly one user" in str(exc.value)


@patch("reconcile.queries.get_users_by")
def test_gpg_encrypt_user_no_gpg_key(
    get_users_by_mock: MagicMock, secret_reader: MagicMock
) -> None:
    target_user = "testuser"
    command = craft_command(
        command_data=GPGEncryptCommandData(
            vault_secret_path="/tmp/tmp",
            target_user=target_user,
        ),
        secret_reader=secret_reader,
    )
    get_users_by_mock.side_effect = [[{"org_username": target_user}]]

    with pytest.raises(UserException) as exc:
        command.execute()
    assert "associated GPG key" in str(exc.value)


def test_gpg_encrypt_no_secret_specified(secret_reader: MagicMock) -> None:
    command = craft_command(
        command_data=GPGEncryptCommandData(
            target_user="one_user",
        ),
        secret_reader=secret_reader,
    )

    with pytest.raises(ArgumentException) as exc:
        command.execute()
    assert "No argument given" in str(exc.value)
