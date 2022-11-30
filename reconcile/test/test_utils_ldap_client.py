import ldap3
import pytest

from reconcile.utils.ldap_client import LdapClient


@pytest.fixture
def connection_search_result():
    result = [
        {"attributes": {"uid": ["user1"]}},
        {"attributes": {"uid": ["user2"]}},
        {"attributes": {"uid": ["user3"]}},
    ]
    return result


def test_ldap_client_from_settings(mocker):
    mock_connection_bind = mocker.patch(
        "reconcile.utils.ldap_client.Connection", autospec=True
    )

    settings = {"ldap": {"baseDn": "test", "serverUrl": "testUrl"}}
    with LdapClient.from_settings(settings) as ldap_client:
        assert ldap_client.base_dn == "test"
        assert mock_connection_bind.call_args.args[0].host == "testUrl"


def test_ldap_client(mocker, connection_search_result):
    mocked_connection = mocker.Mock(spec=ldap3.Connection)
    mocked_connection.search.return_value = None, None, connection_search_result, None

    with LdapClient("test", mocked_connection) as ldap_client:
        assert ldap_client.base_dn == "test"

    mocked_connection.bind.assert_called_once_with()
    mocked_connection.unbind.assert_called_once_with()


def test_ldap_client_get_users(mocker, connection_search_result):
    mocked_connection = mocker.Mock(spec=ldap3.Connection)
    mocked_connection.search.return_value = None, None, connection_search_result, None

    with LdapClient("test", mocked_connection) as ldap_client:
        uids = ["user1", "user2", "user3"]
        ldap_client.get_users(uids)

    mocked_connection.search.assert_called_once_with(
        "test",
        "(&(objectclass=person)(|(uid=user1)(uid=user2)(uid=user3)))",
        attributes=["uid"],
    )
