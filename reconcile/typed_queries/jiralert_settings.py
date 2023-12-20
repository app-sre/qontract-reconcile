from collections.abc import Callable

from reconcile.gql_definitions.common.jiralert_settings import (
    JiralertSettingsV1,
    query,
)
from reconcile.utils import gql
from reconcile.utils.exceptions import AppInterfaceSettingsError


def get_jiralert_settings(
    query_func: Callable | None = None,
) -> JiralertSettingsV1:
    """Returns App Interface Settings and raises err if none are found"""
    if not query_func:
        query_func = gql.get_api().query
    data = query(query_func)
    if data.settings and len(data.settings) == 1:
        if data.settings[0].jiralert:
            return data.settings[0].jiralert
        return JiralertSettingsV1(defaultIssueType="Task", defaultReopenState="To Do")
    raise AppInterfaceSettingsError("jira settings not uniquely defined.")
