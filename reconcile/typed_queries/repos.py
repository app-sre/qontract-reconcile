from collections.abc import Callable

from reconcile.gql_definitions.common.app_code_component_repos import (
    AppCodeComponentsV1,
    query,
)
from reconcile.utils import gql


def get_code_components(
    server: str = "",
    query_func: Callable | None = None,
) -> list[AppCodeComponentsV1]:
    if not query_func:
        query_func = gql.get_api().query
    code_components: list[AppCodeComponentsV1] = []
    for app in query(query_func).apps or []:
        code_components += [
            c for c in app.code_components or [] if c.url.startswith(server)
        ]
    return code_components


def get_repos(
    server: str = "",
    query_func: Callable | None = None,
) -> list[str]:
    code_components = get_code_components(server=server, query_func=query_func)
    return [c.url for c in code_components]
