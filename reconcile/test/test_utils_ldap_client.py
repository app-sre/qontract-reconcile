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


def test_ldap_client(mocker, connection_search_result):
    mock_connection_bind = mocker.patch.object(Connection, "bind", autospec=True)
    mock_connection_unbind = mocker.patch.object(Connection, "unbind", autospec=True)
    mock_connection_search = mocker.patch.object(Connection, "search", autospec=True)
    mock_connection_search.return_value = None, None, connection_search_result, None

    settings = {"ldap": {"baseDn": "test", "serverUrl": "testUrl"}}
    with LdapClient(settings) as ldap_client:
        assert ldap_client.base_dn == "test"
        assert ldap_client.server_url == "testUrl"

    mock_connection_bind.assert_called_once()
    mock_connection_unbind.assert_called_once()


def test_ldap_client_search_filter_by_person():
    assert (
        "(&(objectclass=person)(|(uid=user1)(uid=user2)(uid=user3)))"
        == LdapClient.apply_search_filter_by_person(["user1", "user2", "user3"])
    )


def test_ldap_client_get_users(mocker, connection_search_result):
    mocker.patch.object(Connection, "bind", autospec=True)
    mocker.patch.object(Connection, "unbind", autospec=True)
    mock_connection_search = mocker.patch.object(Connection, "search", autospec=True)
    mock_connection_search.return_value = None, None, connection_search_result, None

    settings = {"ldap": {"baseDn": "test", "serverUrl": "testUrl"}}
    with LdapClient(settings) as ldap_client:
        assert ldap_client.base_dn == "test"
        assert ldap_client.server_url == "testUrl"
        uids = ["user1", "user2", "user3"]
        ldap_client.get_users(uids)

    mock_connection_search.assert_called_once()
