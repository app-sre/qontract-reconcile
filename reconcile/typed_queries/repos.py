from collections.abc import Callable
from typing import Optional

from reconcile.gql_definitions.common.app_code_component_repos import query
from reconcile.utils import gql


def get_repos(
    server: str = "",
    query_func: Optional[Callable] = None,
) -> list[str]:
    if not query_func:
        query_func = gql.get_api().query
    repos: list[str] = []
    for app in query(query_func).apps or []:
        repos += [c.url for c in app.code_components or [] if c.url.startswith(server)]
    return repos
