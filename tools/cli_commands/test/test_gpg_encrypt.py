from unittest.mock import MagicMock, mock_open, patch

import pytest
from reconcile.utils.secret_reader import SecretReader
from tools.cli_commands.gpg_encrypt import (
    ArgumentException,
    GPGEncryptCommand,
    GPGEncryptCommandData,
    UserNotFoundException,
)


def gpg_encrypt_dummy(content: str, public_gpg_key: str) -> str:
    return f"{public_gpg_key}_{content}".replace("\n", "")


@pytest.fixture
def command() -> GPGEncryptCommand:
    secret_reader = MagicMock(spec=SecretReader)
    secret_reader.read_all = MagicMock()
    secret_reader.read_all.side_effect = '{"x":"y"}'
    command = GPGEncryptCommand.create(
        command_data=GPGEncryptCommandData(
            vault_secret_path="",
            vault_secret_version=-1,
            secret_file_path="",
            output="",
            target_user="x",
        ),
        users=[{"x": "y"}],
        secret_reader=secret_reader,
        gpg_encrypt_func=gpg_encrypt_dummy,
    )
    return command


def test_gpg_encrypt_from_vault(command):
    vault_secret_path = "app-sre/test"
    target_user = "testuser"
    gpg_key = "xyz"
    users = [
        {
            "org_username": target_user,
            "public_gpg_key": gpg_key,
        },
        {
            "org_username": "other_user",
            "public_gpg_key": "other_key",
        },
    ]
    command._command_data = GPGEncryptCommandData(
        vault_secret_path=vault_secret_path,
        vault_secret_version=-1,
        target_user=target_user,
        secret_file_path="",
        output="",
    )
    command._users = users
    command.execute()
    command._secret_reader.read_all.assert_called_once_with({"path": vault_secret_path})


def test_gpg_encrypt_from_vault_with_version(command):
    vault_secret_path = "app-sre/test"
    target_user = "testuser"
    gpg_key = "xyz"
    users = [
        {
            "org_username": target_user,
            "public_gpg_key": gpg_key,
        },
        {
            "org_username": "other_user",
            "public_gpg_key": "other_key",
        },
    ]
    command._command_data = GPGEncryptCommandData(
        vault_secret_path=vault_secret_path,
        vault_secret_version=4,
        target_user=target_user,
        secret_file_path="",
        output="",
    )
    command._users = users
    command.execute()
    command._secret_reader.read_all.assert_called_once_with(
        {"path": vault_secret_path, "version": '4'}
    )


@patch("builtins.open", new_callable=mock_open, read_data="test-data")
def test_gpg_encrypt_from_file(mock_file, command, capsys):
    target_user = "testuser"
    gpg_key = "xyz"
    users = [
        {
            "org_username": target_user,
            "public_gpg_key": gpg_key,
        },
        {
            "org_username": "other_user",
            "public_gpg_key": "other_key",
        },
    ]
    command._command_data = GPGEncryptCommandData(
        vault_secret_path="",
        vault_secret_version=-1,
        target_user=target_user,
        secret_file_path="/tmp/tmp",
        output="",
    )
    command._users = users
    command.execute()
    captured = capsys.readouterr()
    assert captured.out == f"{gpg_key}_test-data\n"
    mock_file.assert_called_with("/tmp/tmp")
    command._secret_reader.read_all.assert_not_called()


def test_gpg_encrypt_user_not_found(command):
    users = [
        {
            "org_username": "one_user",
            "public_gpg_key": "one_key",
        },
        {
            "org_username": "other_user",
            "public_gpg_key": "other_key",
        },
    ]
    command._command_data = GPGEncryptCommandData(
        vault_secret_path="app-sre/test",
        vault_secret_version=-1,
        target_user="does_not_exist",
        secret_file_path="",
        output="",
    )
    command._users = users
    with pytest.raises(UserNotFoundException):
        command.execute()


def test_gpg_encrypt_no_secret_specified(command):
    users = [
        {
            "org_username": "one_user",
            "public_gpg_key": "one_key",
        },
    ]
    command._command_data = GPGEncryptCommandData(
        vault_secret_path="",
        vault_secret_version=-1,
        target_user="one_user",
        secret_file_path="",
        output="",
    )
    command._users = users
    with pytest.raises(ArgumentException):
        command.execute()
