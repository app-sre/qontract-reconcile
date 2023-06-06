from typing import Any

import ldap3
import pytest
from pytest_mock import MockerFixture

from reconcile.utils.ldap_client import LdapClient


@pytest.fixture
def connection_search_result() -> list[dict[str, Any]]:
    result = [
        {
            "attributes": {
                "uid": ["user1"],
                "memberOf": [
                    "cn=group1,dc=example,dc=com",
                    "cn=group2,dc=example,dc=com",
                ],
            }
        },
        {
            "attributes": {
                "uid": ["user2"],
                "memberOf": [
                    "cn=group1,dc=example,dc=com",
                    "cn=some-other-group,dc=example,dc=com",
                ],
            }
        },
        {"attributes": {"uid": ["user3"], "memberOf": ["cn=group3,dc=example,dc=com"]}},
    ]
    return result


def test_ldap_client_from_settings(mocker: MockerFixture) -> None:
    mock_connection_bind = mocker.patch(
        "reconcile.utils.ldap_client.Connection", autospec=True
    )

    settings = {"ldap": {"baseDn": "test", "serverUrl": "testUrl"}}
    with LdapClient.from_settings(settings) as ldap_client:
        assert ldap_client.base_dn == "test"
        assert mock_connection_bind.call_args.args[0].host == "testUrl"


def test_ldap_client(
    mocker: MockerFixture, connection_search_result: list[dict[str, Any]]
) -> None:
    mocked_connection = mocker.Mock(spec=ldap3.Connection)
    mocked_connection.search.return_value = None, None, connection_search_result, None

    with LdapClient("test", mocked_connection) as ldap_client:
        assert ldap_client.base_dn == "test"

    mocked_connection.bind.assert_called_once_with()
    mocked_connection.unbind.assert_called_once_with()


def test_ldap_client_get_users(
    mocker: MockerFixture, connection_search_result: list[dict[str, Any]]
) -> None:
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


#
# test get_group_members
#


def test_ldap_client_get_rover_groups(
    mocker: MockerFixture, connection_search_result: list[dict[str, Any]]
) -> None:
    mocked_connection = mocker.Mock(spec=ldap3.Connection)
    mocked_connection.search.return_value = None, None, connection_search_result, None

    with LdapClient("test", mocked_connection) as ldap_client:
        group_dns = {
            "cn=group1,dc=example,dc=com",
            "cn=group2,dc=example,dc=com",
            "cn=group3,dc=example,dc=com",
        }
        groups_by_dn = ldap_client.get_group_members(group_dns)

    # check that the search filter is correct
    mocked_connection.search.assert_called_once_with(
        "test",
        "(|(memberOf=cn=group1,dc=example,dc=com)(memberOf=cn=group2,dc=example,dc=com)(memberOf=cn=group3,dc=example,dc=com))",
        attributes=["uid", "memberOf"],
    )

    assert groups_by_dn == {
        "cn=group1,dc=example,dc=com": {"user1", "user2"},
        "cn=group2,dc=example,dc=com": {"user1"},
        "cn=group3,dc=example,dc=com": {"user3"},
    }
