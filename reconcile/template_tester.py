import difflib
import logging
import sys
import yaml
import reconcile.openshift_base as ob
import reconcile.openshift_resources_base as orb

from reconcile import queries
from reconcile.status import ExitCodes
from reconcile.utils import gql
from reconcile.utils.semver_helper import make_semver


QONTRACT_INTEGRATION = "template-tester"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


TEMPLATE_TESTS_QUERY = """
{
  tests: template_tests_v1 {
    name
    resourcePath
    expectedResult
  }
}
"""


def load_resource(path: str) -> dict:
    return yaml.safe_load(gql.get_resource(path)["content"])


def run(dry_run):
    gqlapi = gql.get_api()
    template_tests = gqlapi.query(TEMPLATE_TESTS_QUERY)["tests"]
    settings = queries.get_app_interface_settings()
    error = False
    for tt in template_tests:
        found = False
        resource_path = tt["resourcePath"]
        expected_result = load_resource(tt["expectedResult"])
        for n in gqlapi.query(orb.NAMESPACES_QUERY)["namespaces"]:
            ob.aggregate_shared_resources(n, "openshiftResources")
            openshift_resources = n.get("openshiftResources")
            if not openshift_resources:
                continue

            for r in openshift_resources:
                if resource_path != r.get("resource", {}).get("path"):
                    continue

                found = True
                openshift_resource = orb.fetch_openshift_resource(r, n, settings)
                if openshift_resource.body != expected_result:
                    diff = difflib.unified_diff(
                        yaml.safe_dump(expected_result).splitlines(keepends=True),
                        yaml.safe_dump(openshift_resource.body).splitlines(
                            keepends=True
                        ),
                        "expected",
                        "rendered",
                    )
                    logging.error(
                        f"rendered template is different from expected result in template test {tt['name']}:\n"
                        f"{''.join(diff)}"
                    )
                    error = True

        if not found:
            logging.error(
                f"resource defined in template tests {tt['name']} is not referenced from any namespaces"
            )
            error = True

    if error:
        sys.exit(ExitCodes.ERROR)
