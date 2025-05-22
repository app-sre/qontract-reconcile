from collections.abc import Callable

from reconcile.gql_definitions.common.ldap_settings import (
    LdapSettingsV1,
    query,
)
from reconcile.utils import gql
from reconcile.utils.exceptions import AppInterfaceSettingsError


def get_ldap_settings(
    query_func: Callable | None = None,
) -> LdapSettingsV1:
    """Returns App Interface Settings and raises err if none are found"""
    if not query_func:
        query_func = gql.get_api().query
    data = query(query_func)
    if data.settings and len(data.settings) == 1 and data.settings[0].ldap:
        return data.settings[0].ldap
    raise AppInterfaceSettingsError("Ldap settings is not defined.")
