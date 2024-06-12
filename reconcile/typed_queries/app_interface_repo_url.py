from collections.abc import Callable

from reconcile.gql_definitions.common.app_interface_repo_settings import query
from reconcile.utils import gql
from reconcile.utils.exceptions import AppInterfaceSettingsError


def get_app_interface_repo_url(query_func: Callable | None = None) -> str:
    if not query_func:
        gqlapi = gql.get_api()
        query_func = gqlapi.query
    data = query(query_func=query_func)
    if data.settings and len(data.settings) == 1:
        return data.settings[0].repo_url
    raise AppInterfaceSettingsError("repoUrl not uniquely defined")
