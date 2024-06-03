from reconcile.gql_definitions.jira.jira_servers import JiraServerV1, query
from reconcile.utils import gql


def get_jira_servers() -> list[JiraServerV1]:
    data = query(gql.get_api().query)
    return list(data.jira_servers or [])
