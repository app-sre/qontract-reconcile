from abc import (
    ABC,
    abstractmethod,
)

from qontract_utils.ldap_api import LdapApi

from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.ldap_settings import get_ldap_settings
from reconcile.utils.secret_reader import create_secret_reader


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

    def __init__(self, ldap_client: LdapApi, group_base_dn: str) -> None:
        self.ldap_client = ldap_client
        self.group_base_dn = group_base_dn

    def resolve_groups(self, group_ids: set[str]) -> dict[str, set[str]]:
        if not group_ids:
            return {}
        with self.ldap_client as lc:
            groups = lc.get_group_members({
                f"cn={cn},{self.group_base_dn}" for cn in group_ids
            })
        return {group.cn: {user.username for user in group.members} for group in groups}


def init_ldap_group_member_provider(group_base_dn: str) -> LdapGroupMemberProvider:
    """
    Initialize a LDAPGroupMemberProvider using the available settings.
    Right now, it depends on the app-interface settings.

    The group_base_dn is used to find groups by their CN. It is extended as folows
    to find a group by name:
        cn={name},{group_base_dn}
    """

    settings = get_ldap_settings()
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    bind_dn = None
    bind_password = None
    if settings.credentials:
        ldap_credentials = secret_reader.read_all_secret(settings.credentials)
        if "bind_dn" not in ldap_credentials or "bind_password" not in ldap_credentials:
            raise ValueError(
                "LDAP credentials must contain 'bind_dn' and 'bind_password'"
            )
        bind_dn = ldap_credentials["bind_dn"]
        bind_password = ldap_credentials["bind_password"]
    return LdapGroupMemberProvider(
        LdapApi(
            server_url=settings.server_url,
            base_dn=settings.base_dn,
            bind_dn=bind_dn,
            bind_password=bind_password,
        ),
        group_base_dn,
    )
