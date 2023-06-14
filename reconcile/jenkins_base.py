from reconcile import queries
from reconcile.utils import gql
from reconcile.utils.jenkins_api import JenkinsApi
from reconcile.utils.secret_reader import SecretReader

INSTANCES_QUERY = """
{
  instances: jenkins_instances_v1 {
    name
    token {
      path
      field
      version
      format
    }
  }
}
"""


def get_jenkins_map() -> dict[str, JenkinsApi]:
    gqlapi = gql.get_api()
    jenkins_instances = gqlapi.query(INSTANCES_QUERY)["instances"]
    secret_reader = SecretReader(queries.get_secret_reader_settings())

    jenkins_map = {}
    for instance in jenkins_instances:
        instance_name = instance["name"]
        if instance_name in jenkins_map:
            continue

        token = instance["token"]
        jenkins = JenkinsApi.init_jenkins_from_secret(secret_reader, token)
        jenkins_map[instance_name] = jenkins

    return jenkins_map
