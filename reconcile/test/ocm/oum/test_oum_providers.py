import pytest
from pytest_mock import MockerFixture

from reconcile.oum.providers import LdapGroupMemberProvider
from reconcile.utils.ldap_client import LdapClient


@pytest.fixture
def mock_ldap_client(mocker: MockerFixture) -> LdapClient:
    lc = mocker.Mock(spec=LdapClient, autospec=True)
    lc.return_value.get_group_members.return_value = {
        "cn=group1,dc=example,dc=com": {"user1", "user2"},
        "cn=group2,dc=example,dc=com": {"user3", "user4"},
    }
    lc.__enter__ = lc
    lc.__exit__ = mocker.Mock(return_value=None)
    return lc


def test_ldap_group_member_provider(mock_ldap_client: LdapClient) -> None:
    provider = LdapGroupMemberProvider(mock_ldap_client, "dc=example,dc=com")
    groups = provider.resolve_groups({"group1", "group2"})
    assert "group1" in groups
    assert groups["group1"] == {"user1", "user2"}
    assert "group2" in groups
    assert groups["group2"] == {"user3", "user4"}


def test_ldap_group_member_provider_empty_list(mock_ldap_client: LdapClient) -> None:
    provider = LdapGroupMemberProvider(mock_ldap_client, "dc=example,dc=com")
    groups = provider.resolve_groups(set())
    assert groups == {}
