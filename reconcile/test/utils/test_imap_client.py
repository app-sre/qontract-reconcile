from typing import Any

import pytest

from reconcile.utils.imap_client import ImapClient


@pytest.fixture
def patch_secret_reader(mocker):
    return mocker.patch(
        "reconcile.utils.secret_reader.SecretReader.read_all",
        return_value={
            "server": "server_mock",
            "port": 10000,
            "username": "username_mock",
            "password": "password_mock",
        },
        autospec=True,
    )


@pytest.fixture
def settings(mocker):
    return {"imap": {"credentials": "foobar"}}


@pytest.fixture
def mock_imap_server(mocker):
    mock_imap = mocker.patch("imaplib.IMAP4_SSL", autospec=True)
    mock_imap.return_value.search.return_value = ["Ok", [b"1 2"]]
    mock_imap.return_value.uid.side_effect = [
        ("Ok", [["1", b"mail message"]]),
        ("Ok", [["2", b"mail message"]]),
    ]
    return mock_imap


@pytest.fixture
def imap_client(settings: dict[str, Any], patch_secret_reader, mock_imap_server):
    return ImapClient(settings)


def test_imap_client_init_and_getting_imap_config(imap_client: ImapClient):
    assert imap_client.host == "server_mock"
    assert imap_client.user == "username_mock"
    assert imap_client.password == "password_mock"
    assert imap_client.port == 10000
    assert imap_client.timeout == 30


def test_imap_client_context_manager(imap_client: ImapClient):
    with imap_client as _client:
        assert _client._server


def test_imap_client_enforce_context_manager_usage(imap_client: ImapClient):
    assert not imap_client._server


def test_imap_client_get_mails(imap_client: ImapClient):
    with imap_client as _client:
        assert _client.get_mails() == [
            {"msg": "mail message", "uid": b"1"},
            {"msg": "mail message", "uid": b"2"},
        ]
