import pytest

from reconcile import ldap_users


@pytest.fixture
def mocked_queries_get_users(mocker):
    queries_get_users_mock = mocker.patch.object(ldap_users.queries, "get_users", autospec=True)
    queries_get_users_mock.return_value = [
        {'org_username': 'username1',
         'requests': [{'path': 'test_path1'}],
         'queries': [{'path': 'another_test_path1'}],
         'gabi_instances': [{'path': 'yet_another_test_path1'}],
         'path': 'blah'
         },
        {'org_username': 'username2',
         'requests': [{'path': 'test_path2'}],
         'queries': [{'path': 'another_test_path2'}],
         'gabi_instances': [{'path': 'yet_another_test_path2'}],
         'path': 'blah'
         },
        {'org_username': 'username3',
         'requests': [{'path': 'test_path3'}],
         'queries': [{'path': 'another_test_path3'}],
         'gabi_instances': [{'path': 'yet_another_test_path3'}],
         'path': 'blah'
         }
    ]

    return queries_get_users_mock


@pytest.fixture
def mocked_queries_get_app_interface_settings(mocker):
    queries_get_app_interface_settings = mocker.patch.object(ldap_users.queries, "get_app_interface_settings",
                                                             autospec=True)
    queries_get_app_interface_settings.return_value = {}
    return queries_get_app_interface_settings


@pytest.fixture
def mocked_ldap_client(mocker):
    mock_ldap_client = mocker.patch.object(ldap_users.LdapClient, "from_settings", autospec=True)
    dummy_ldap_client = mocker.Mock(spec=ldap_users.LdapClient)
    dummy_ldap_client.__enter__ = dummy_ldap_client
    dummy_ldap_client.__exit__ = mocker.Mock(return_value=None)
    dummy_ldap_client.return_value.get_users.return_value = {'username1', 'username2'}
    mock_ldap_client.return_value = dummy_ldap_client
    return mock_ldap_client


@pytest.fixture
def mocked_mr_client_gateway(mocker):
    mock_mr_client_gateway = mocker.patch.object(ldap_users.mr_client_gateway, "init", autospec=True)
    return mock_mr_client_gateway


@pytest.fixture
def mocked_create_delete_user(mocker):
    mock_create_delete_user = mocker.patch('reconcile.ldap_users.CreateDeleteUser', autospec=True)
    return mock_create_delete_user


def test_ldap_users_no_dry_run(mocker, mocked_queries_get_users, mocked_queries_get_app_interface_settings,
                               mocked_ldap_client, mocked_mr_client_gateway, mocked_create_delete_user):

    ldap_users.run(False, None)

    mocked_mr_client_gateway.assert_called_once()
    mocked_create_delete_user.assert_called_once()
    assert mocked_create_delete_user.call_args == mocker.call('username3', [{'type': 0, 'path': 'datablah'},
                                                                          {'type': 1, 'path': 'datatest_path3'},
                                                                          {'type': 2, 'path': 'dataanother_test_path3'},
                                                                          {'type': 3,
                                                                           'path': 'datayet_another_test_path3'}])
    assert mocked_create_delete_user.method_calls[0][0] == '().submit'


def test_ldap_users_dry_run(mocked_queries_get_users, mocked_queries_get_app_interface_settings,
                            mocked_ldap_client, mocked_mr_client_gateway, mocked_create_delete_user):

    ldap_users.run(True, None)

    assert mocked_mr_client_gateway.call_count == 0
    assert mocked_create_delete_user.call_count == 0
