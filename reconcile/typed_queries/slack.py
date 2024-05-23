from reconcile.gql_definitions.common.slack_workspaces import SlackWorkspaceV1, query
from reconcile.utils import gql


def get_slack_workspaces() -> list[SlackWorkspaceV1]:
    data = query(gql.get_api().query)
    return list(data.workspaces or [])
