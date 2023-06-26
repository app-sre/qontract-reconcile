import pytest

from reconcile import ldap_users


@pytest.fixture
def patched_queries_get_users(mocker):
    queries_get_users_mock = mocker.patch.object(
        ldap_users.queries, "get_users", autospec=True
    )
    queries_get_users_mock.return_value = [
        {
            "org_username": "username1",
            "requests": [{"path": "test_path1"}],
            "queries": [{"path": "another_test_path1"}],
            "gabi_instances": [{"path": "yet_another_test_path1"}],
            "path": "blah",
        },
        {
            "org_username": "username2",
            "requests": [{"path": "test_path2"}],
            "queries": [{"path": "another_test_path2"}],
            "gabi_instances": [{"path": "yet_another_test_path2"}],
            "path": "blah",
        },
        {
            "org_username": "username3",
            "requests": [{"path": "test_path3"}],
            "queries": [{"path": "another_test_path3"}],
            "gabi_instances": [{"path": "yet_another_test_path3"}],
            "path": "blah",
        },
    ]

    return queries_get_users_mock


@pytest.fixture
def patched_queries_get_app_interface_settings(mocker):
    queries_get_app_interface_settings = mocker.patch.object(
        ldap_users, "get_ldap_settings", autospec=True
    )
    queries_get_app_interface_settings.return_value = {}
    return queries_get_app_interface_settings


@pytest.fixture
def mocked_ldap_client(mocker):
    mock_ldap_client = mocker.patch.object(
        ldap_users.LdapClient, "from_settings", autospec=True
    )
    dummy_ldap_client = mocker.Mock(spec=ldap_users.LdapClient)
    dummy_ldap_client.__enter__ = dummy_ldap_client
    dummy_ldap_client.__exit__ = mocker.Mock(return_value=None)
    dummy_ldap_client.return_value.get_users.return_value = {"username1", "username2"}
    mock_ldap_client.return_value = dummy_ldap_client
    return mock_ldap_client


@pytest.fixture
def patched_mr_client_gateway(mocker):
    mock_mr_client_gateway = mocker.patch.object(
        ldap_users.mr_client_gateway, "init", autospec=True
    )
    return mock_mr_client_gateway


@pytest.fixture
def patched_create_delete_user(mocker):
    mock_create_delete_user = mocker.patch(
        "reconcile.ldap_users.CreateDeleteUserAppInterface", autospec=True
    )
    return mock_create_delete_user


@pytest.fixture
def patched_create_delete_user_infra(mocker):
    mock_create_delete_user_infra = mocker.patch(
        "reconcile.ldap_users.CreateDeleteUserInfra", autospec=True
    )
    return mock_create_delete_user_infra


def test_ldap_users_no_dry_run(
    mocker,
    patched_queries_get_users,
    patched_queries_get_app_interface_settings,
    mocked_ldap_client,
    patched_mr_client_gateway,
    patched_create_delete_user,
    patched_create_delete_user_infra,
):
    ldap_users.run(False, None, None)

    assert patched_mr_client_gateway.call_count == 2
    patched_create_delete_user.assert_called_once_with(
        "username3",
        [
            {"path": "datablah", "type": 0},
            {"path": "datatest_path3", "type": 1},
            {"path": "dataanother_test_path3", "type": 2},
            {"path": "datayet_another_test_path3", "type": 3},
        ],
    )
    assert patched_create_delete_user.method_calls[0][0] == "().submit"
    assert patched_create_delete_user_infra.method_calls[0][0] == "().submit"


def test_ldap_users_dry_run(
    patched_queries_get_users,
    patched_queries_get_app_interface_settings,
    mocked_ldap_client,
    patched_mr_client_gateway,
    patched_create_delete_user,
    patched_create_delete_user_infra,
):
    ldap_users.run(True, None, None)

    patched_mr_client_gateway.assert_not_called()
    patched_create_delete_user.assert_not_called()
    patched_create_delete_user_infra.assert_not_called()
