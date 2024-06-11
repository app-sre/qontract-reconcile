from collections.abc import Callable

from reconcile.gql_definitions.common.app_interface_vault_settings import (
    AppInterfaceSettingsV1,
    query,
)
from reconcile.utils import gql
from reconcile.utils.exceptions import AppInterfaceSettingsError


def get_app_interface_vault_settings(
    query_func: Callable | None = None,
) -> AppInterfaceSettingsV1:
    """Returns App Interface Settings and raises err if none are found"""
    if not query_func:
        query_func = gql.get_api().query
    data = query(query_func=query_func)
    if data.vault_settings and len(data.vault_settings) == 1:
        return data.vault_settings[0]
    raise AppInterfaceSettingsError("vault settings not uniquely defined.")
