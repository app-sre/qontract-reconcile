import pytest
from pytest_mock import MockerFixture
from qontract_utils.ldap_api import LdapApi
from qontract_utils.ldap_api.models import LdapGroup, LdapUser

from reconcile.oum.providers import LdapGroupMemberProvider


@pytest.fixture
def mock_ldap_client(mocker: MockerFixture) -> LdapApi:
    lc = mocker.Mock(spec=LdapApi, autospec=True)
    lc.return_value.get_group_members.return_value = [
        LdapGroup(
            cn="group1",
            dn="cn=group1,dc=example,dc=com",
            members=frozenset({
                LdapUser(username="user1"),
                LdapUser(username="user2"),
            }),
        ),
        LdapGroup(
            cn="group2",
            dn="cn=group2,dc=example,dc=com",
            members=frozenset({
                LdapUser(username="user3"),
                LdapUser(username="user4"),
            }),
        ),
    ]
    lc.__enter__ = lc
    lc.__exit__ = mocker.Mock(return_value=None)
    return lc


def test_ldap_group_member_provider(mock_ldap_client: LdapApi) -> None:
    provider = LdapGroupMemberProvider(mock_ldap_client, "dc=example,dc=com")
    groups = provider.resolve_groups({"group1", "group2"})
    assert "group1" in groups
    assert groups["group1"] == {"user1", "user2"}
    assert "group2" in groups
    assert groups["group2"] == {"user3", "user4"}


def test_ldap_group_member_provider_empty_list(mock_ldap_client: LdapApi) -> None:
    provider = LdapGroupMemberProvider(mock_ldap_client, "dc=example,dc=com")
    groups = provider.resolve_groups(set())
    assert groups == {}
