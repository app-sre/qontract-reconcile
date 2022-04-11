import logging
import sys
import yaml
import reconcile.openshift_resources_base as orb

from textwrap import indent
from reconcile.status import ExitCodes
from reconcile.utils import gql
from reconcile.utils.semver_helper import make_semver


QONTRACT_INTEGRATION = "template-tester"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


TEMPLATE_TESTS_QUERY = """
{
  tests: template_tests_v1 {
    name
    resource {
      %s
    }
    resourceParent {
      name
      cluster {
        name
      }
    }
    expectedResult
  }
}
""" % indent(
    orb.OPENSHIFT_RESOURCE, 2 * " "
)


def load_resource(path: str) -> dict:
    return yaml.safe_load(gql.get_resource(path)["content"])


def run(dry_run):
    gqlapi = gql.get_api()
    template_tests = gqlapi.query(TEMPLATE_TESTS_QUERY)["tests"]
    error = False
    for tt in template_tests:
        resource = tt["resource"]
        resource["add_path_to_prom_rules"] = False
        parent = load_resource(tt["resourceParent"])
        openshift_resource = orb.fetch_openshift_resource(tt["resource"], parent)
        expected_result = load_resource(tt["expectedResult"])
        if openshift_resource.body != expected_result:
            logging.error(
                f"rendered template is different from expected result in template test {tt['name']}:\n"
                f"rendered:\n{yaml.safe_dump(openshift_resource.body)}\n"
                f"expected result:\n{yaml.safe_dump(expected_result)}"
            )
            error = True

    if error:
        sys.exit(ExitCodes.ERROR)
