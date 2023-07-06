from reconcile.gql_definitions.common.jira_settings import (
    AppInterfaceSettingsV1,
    query,
)
from reconcile.utils.exceptions import AppInterfaceSettingsError
from reconcile.utils.gql import GqlApi


def get_jira_settings(
    gql_api: GqlApi,
) -> AppInterfaceSettingsV1:
    """Returns App Interface Settings and raises err if none are found"""
    data = query(query_func=gql_api.query)
    if data.jira_settings and len(data.jira_settings) == 1:
        return data.jira_settings[0]
    raise AppInterfaceSettingsError("jira settings not uniquely defined.")
