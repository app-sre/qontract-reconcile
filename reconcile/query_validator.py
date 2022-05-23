from reconcile.utils import gql
from reconcile.utils.semver_helper import make_semver


QONTRACT_INTEGRATION = "query-validator"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


QUERY_VALIDATIONS_QUERY = """
{
  validations: query_validations_v1 {
    name
    queries {
      path
    }
  }
}
"""


def run(dry_run):
    gqlapi = gql.get_api()
    query_validations = gqlapi.query(QUERY_VALIDATIONS_QUERY)["validations"]
    for qv in query_validations:
        for q in qv["queries"]:
            gqlapi.query(gql.get_resource(q["path"])["content"])
