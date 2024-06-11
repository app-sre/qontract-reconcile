from collections.abc import Callable

from reconcile.gql_definitions.external_resources.external_resources_modules import (
    ExternalResourcesModuleV1,
)
from reconcile.gql_definitions.external_resources.external_resources_modules import (
    query as query_modules,
)
from reconcile.gql_definitions.external_resources.external_resources_namespaces import (
    NamespaceV1,
)
from reconcile.gql_definitions.external_resources.external_resources_namespaces import (
    query as query_namespaces,
)
from reconcile.gql_definitions.external_resources.external_resources_settings import (
    ExternalResourcesSettingsV1,
)
from reconcile.gql_definitions.external_resources.external_resources_settings import (
    query as query_settings,
)
from reconcile.utils import gql


def get_namespaces(query_func: Callable | None = None) -> list[NamespaceV1]:
    if not query_func:
        query_func = gql.get_api().query
    data = query_namespaces(query_func=query_func)
    return list(data.namespaces or [])


def get_settings(
    query_func: Callable | None = None,
) -> list[ExternalResourcesSettingsV1]:
    if not query_func:
        query_func = gql.get_api().query
    data = query_settings(query_func=query_func)
    return list(data.settings or [])


def get_modules(
    query_func: Callable | None = None,
) -> list[ExternalResourcesModuleV1]:
    if not query_func:
        query_func = gql.get_api().query
    data = query_modules(query_func=query_func)
    return list(data.modules or [])
