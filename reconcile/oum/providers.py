from abc import (
    ABC,
    abstractmethod,
)

from reconcile.ldap_users import get_ldap_settings
from reconcile.utils.ldap_client import LdapClient


class GroupMemberProvider(ABC):
    """
    The base class for all group member providers.
    """

    @abstractmethod
    def resolve_groups(self, group_ids: set[str]) -> dict[str, set[str]]:
        """
        Resolve the set of members for each given group ID.
        """


class LdapGroupMemberProvider(GroupMemberProvider):
    """
    Resolve group members using the LDAP groups.
    """

    def __init__(self, ldap_client: LdapClient, group_base_dn: str):
        self.ldap_client = ldap_client
        self.group_base_dn = group_base_dn

    def resolve_groups(self, group_ids: set[str]) -> dict[str, set[str]]:
        group_dn_mapping = {f"cn={cn},{self.group_base_dn}": cn for cn in group_ids}
        if len(group_ids) == 0:
            return {}
        with self.ldap_client as lc:
            groups_members_by_dn = lc.get_group_members(group_dn_mapping.keys())
        return {
            group_dn_mapping[dn]: members
            for dn, members in groups_members_by_dn.items()
        }


def init_ldap_group_member_provider(group_base_dn: str) -> LdapGroupMemberProvider:
    """
    Initialize a LDAPGroupMemberProvider using the available settings.
    Right now, it depends on the app-interface settings.

    The group_base_dn is used to find groups by their CN. It is extended as folows
    to find a group by name:
        cn={name},{group_base_dn}
    """

    settings = get_ldap_settings()
    return LdapGroupMemberProvider(
        LdapClient.from_params(
            settings["ldap"]["serverUrl"], None, None, settings["ldap"]["baseDn"]
        ),
        group_base_dn,
    )
