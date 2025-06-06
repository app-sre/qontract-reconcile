from collections.abc import Callable

from reconcile.gql_definitions.common.rhcs_provider_settings import (
    RhcsProviderSettingsV1,
    query,
)
from reconcile.utils import gql
from reconcile.utils.exceptions import AppInterfaceSettingsError


def get_rhcs_provider_settings(
    query_func: Callable | None = None,
) -> RhcsProviderSettingsV1:
    """Returns App Interface Settings and raises err if none are found"""
    if not query_func:
        query_func = gql.get_api().query
    data = query(query_func)
    if data.settings and len(data.settings) == 1:
        if data.settings[0].rhcs_provider:
            return data.settings[0].rhcs_provider
    raise AppInterfaceSettingsError("RHCS provider settings not uniquely defined.")
