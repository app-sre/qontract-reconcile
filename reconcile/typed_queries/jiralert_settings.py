from reconcile.gql_definitions.common.jiralert_settings import (
    JiralertSettingsV1,
    query,
)
from reconcile.utils.exceptions import AppInterfaceSettingsError
from reconcile.utils.gql import GqlApi


def get_jiralert_settings(
    gql_api: GqlApi,
) -> JiralertSettingsV1:
    """Returns App Interface Settings and raises err if none are found"""
    data = query(query_func=gql_api.query)
    if data.settings and len(data.settings) == 1:
        if data.settings[0].jiralert:
            return data.settings[0].jiralert
        return JiralertSettingsV1(defaultIssueType="Task", defaultReopenState="To Do")
    raise AppInterfaceSettingsError("jira settings not uniquely defined.")
