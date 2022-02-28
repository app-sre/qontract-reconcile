from ldap3 import Connection
from reconcile.utils.ldap_client import LdapClient


def test_ldap_client(mocker):
    mock_connection_bind = mocker.patch.object(Connection, "bind", autospec=True)
    mock_connection_unbind = mocker.patch.object(Connection, "unbind", autospec=True)
    mock_connection_search = mocker.patch.object(Connection, "search", autospec=True)
    result = [
        {'attributes': {'uid': ['user1']}},
        {'attributes': {'uid': ['user2']}},
        {'attributes': {'uid': ['user3']}}
    ]
    mock_connection_search.return_value = None, None, result, None

    settings = {'ldap': {
        'baseDn': 'test',
        'serverUrl': 'testUrl'
    }}
    with LdapClient.from_settings(settings) as ldap_client:
        uids = ['user1', 'user2', 'user3']
        ldap_client.get_users(uids)

    mock_connection_search.assert_called_once()
    mock_connection_bind.assert_called_once()
    mock_connection_unbind.assert_called_once()
