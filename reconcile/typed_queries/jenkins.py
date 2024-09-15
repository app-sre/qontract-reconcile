from reconcile.gql_definitions.jenkins_configs.jenkins_configs import (
    JenkinsConfigV1,
)
from reconcile.gql_definitions.jenkins_configs.jenkins_configs import (
    query as jenkins_configs_query,
)
from reconcile.gql_definitions.jenkins_configs.jenkins_instances import (
    JenkinsInstanceV1,
)
from reconcile.gql_definitions.jenkins_configs.jenkins_instances import (
    query as jenkins_instances_query,
)
from reconcile.utils import gql


def get_jenkins_instances() -> list[JenkinsInstanceV1]:
    gqlapi = gql.get_api()
    data = jenkins_instances_query(gqlapi.query)
    return list(data.instances or [])


def get_jenkins_configs() -> list[JenkinsConfigV1]:
    gqlapi = gql.get_api()
    data = jenkins_configs_query(gqlapi.query)
    return list(data.jenkins_configs or [])
