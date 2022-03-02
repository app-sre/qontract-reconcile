import ldap3
import pytest
from ldap3 import Connection
from reconcile.utils.ldap_client import LdapClient


@pytest.fixture
def connection_search_result():
    result = [
        {"attributes": {"uid": ["user1"]}},
        {"attributes": {"uid": ["user2"]}},
        {"attributes": {"uid": ["user3"]}},
    ]
    return result


def test_ldap_client_from_settings(mocker, connection_search_result):
    mock_connection_bind = mocker.patch.object(Connection, "bind", autospec=True)
    mock_connection_unbind = mocker.patch.object(Connection, "unbind", autospec=True)
    mock_connection_search = mocker.patch.object(Connection, "search", autospec=True)
    mock_connection_search.return_value = None, None, connection_search_result, None

    settings = {"ldap": {"baseDn": "test", "serverUrl": "testUrl"}}
    with LdapClient.from_settings(settings) as ldap_client:
        uids = ["user1", "user2", "user3"]
        ldap_client.get_users(uids)

    mock_connection_search.assert_called_once()
    mock_connection_bind.assert_called_once()
    mock_connection_unbind.assert_called_once()


def test_ldap_client(mocker, connection_search_result):
    mocked_connection = mocker.Mock(spec=ldap3.Connection)
    mocked_connection.search.return_value = None, None, connection_search_result, None

    with LdapClient("test", mocked_connection) as ldap_client:
        uids = ["user1", "user2", "user3"]
        ldap_client.get_users(uids)

    mocked_connection.search.assert_called_once()
    mocked_connection.bind.assert_called_once()
    mocked_connection.unbind.assert_called_once()
