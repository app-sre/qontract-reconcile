from reconcile.gql_definitions.gitlab_members.gitlab_instances import (
    GitlabInstanceV1,
    query,
)
from reconcile.utils import gql


def get_gitlab_instances() -> list[GitlabInstanceV1]:
    gqlapi = gql.get_api()
    data = query(gqlapi.query)
    return list(data.instances or [])
