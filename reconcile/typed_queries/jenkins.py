from reconcile.gql_definitions.jenkins_configs.jenkins_instances import (
    JenkinsInstanceV1,
    query,
)
from reconcile.utils import gql


def get_jenkins_instances() -> list[JenkinsInstanceV1]:
    gqlapi = gql.get_api()
    data = query(gqlapi.query)
    return list(data.instances or [])
