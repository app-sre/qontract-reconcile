import json
import logging
import re
import sys
import traceback
import yaml

from sretoolbox.utils import threaded

from reconcile import queries
from reconcile.utils import gql
from reconcile.utils import promtool
import reconcile.openshift_base as ob
import reconcile.openshift_resources_base as orb

from reconcile.utils.semver_helper import make_semver
from reconcile.status import ExitCodes
from reconcile.utils.structs import CommandExecutionResult


QONTRACT_INTEGRATION = "prometheus_rules_tester"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)

PROMETHEUS_RULES_PATHS_QUERY = """
{
  resources: resources_v1(schema: "/openshift/prometheus-rule-1.yml") {
    path
  }
}
"""

PROMETHEUS_RULES_TESTS_QUERY = """
{
  tests: resources_v1(schema: "/app-interface/prometheus-rule-test-1.yml") {
    path
    content
  }
}
"""


def get_prometheus_tests():
    """Returns a path indexed dict with the prometheus tests content"""
    gqlapi = gql.get_api()
    tests = {}
    for t in gqlapi.query(PROMETHEUS_RULES_TESTS_QUERY)["tests"]:
        # This can be a jinja template. We cannot load the yaml here
        tests[t["path"]] = t["content"]

    return tests


# returned structure:
# rules = {
#    'path': {
#        'cluster_name': {
#            'namespace': {
#                'rule_spec': spec
#                'variables: { ... } # openshift resource variables if any
#    (...)
def get_prometheus_rules(cluster_name):
    """Returns a dict of dicts indexed by path with rule data"""
    gqlapi = gql.get_api()
    rules = {}
    for r in gqlapi.query(PROMETHEUS_RULES_PATHS_QUERY)["resources"]:
        rules[r["path"]] = {}

    for n in gqlapi.query(orb.NAMESPACES_QUERY)["namespaces"]:
        cluster = n["name"]
        namespace = n["cluster"]["name"]

        if cluster_name and cluster != cluster_name:
            continue

        if (
            not n.get("managedResourceTypes")
            or "PrometheusRule" not in n["managedResourceTypes"]
        ):
            continue

        ob.aggregate_shared_resources(n, "openshiftResources")
        openshift_resources = n.get("openshiftResources")
        if not openshift_resources:
            logging.warning(
                "No openshiftResources defined for namespace "
                f"{namespace} in cluster {cluster}"
            )
            continue

        for r in openshift_resources:
            path = r["path"]
            if path not in rules:
                continue

            # Or we will get an unexepected and confusing html_url annotation
            if "add_path_to_prom_rules" not in r:
                r["add_path_to_prom_rules"] = False

            openshift_resource = orb.fetch_openshift_resource(resource=r, parent=n)

            if cluster not in rules[path]:
                rules[path][cluster] = {}

            rules[path][cluster][namespace] = {"spec": openshift_resource.body["spec"]}

            # we keep variables to use them in the rule tests
            variables = json.loads(r.get("variables") or "{}")
            # keep the resource as well
            variables["resource"] = r
            rules[path][cluster][namespace]["variables"] = variables

    # We return rules that are actually consumed from a namespace becaused
    # those are the only ones that can be resolved as they can be templates
    return {path: data for path, data in rules.items() if data}


# prometheus rule spec
# spec:
#   groups:
#   - name: name
#     rules:
#     - alert: alertName
#       annotations:
#         ...
#       expr: expression
#       for: duration
#       labels:
#         service: serviceName
#         ...
def check_valid_services(rule):
    """Check that all services in Prometheus rules are known.
    This replaces an enum in the json schema with a list
    in app-interface settings."""
    allowed_services = queries.get_app_interface_settings()["alertingServices"]
    missing_services = set()
    spec = rule["spec"]
    groups = spec["groups"]
    for g in groups:
        group_rules = g["rules"]
        for r in group_rules:
            rule_labels = r.get("labels")
            if not rule_labels:
                continue
            service = rule_labels.get("service")
            if not service:
                continue
            if service not in allowed_services:
                missing_services.add(service)

    if missing_services:
        return CommandExecutionResult(
            False, f"services are missing from alertingServices: {missing_services}"
        )

    return CommandExecutionResult(True, "")


def check_rule(rule):
    promtool_check_result = promtool.check_rule(yaml_spec=rule["spec"])
    valid_services_result = check_valid_services(rule)
    rule["check_result"] = promtool_check_result and valid_services_result
    return rule


def check_prometheus_rules(rules, thread_pool_size):
    """Returns a list of dicts with failed rule checks"""
    # flatten the list of prometheus rules to have a list of dicts
    rules_to_check = []
    for path, cluster_data in rules.items():
        for cluster, namespace_data in cluster_data.items():
            for namespace, rule_data in namespace_data.items():
                rules_to_check.append(
                    {
                        "path": path,
                        "cluster": cluster,
                        "namespace": namespace,
                        "spec": rule_data["spec"],
                    }
                )

    result = threaded.run(
        func=check_rule, iterable=rules_to_check, thread_pool_size=thread_pool_size
    )

    # return invalid rules
    return [rule for rule in result if not rule["check_result"]]


def run_test(test):
    test["check_result"] = promtool.run_test(
        test_yaml_spec=test["test"], rule_files=test["rule_files"]
    )
    return test


def get_rule_files_from_jinja_test_template(template):
    """Parse test template to get prometheus rule files paths"""
    rule_files = []
    try:
        parsed = yaml.safe_load(template)
        rule_files = parsed["rule_files"]
    except Exception:
        # The jinja template is not valid yaml :(
        # A poor man's approach is used to get the rule files
        # Let's assume people will follow the examples and use yaml lists as:
        # rule_files:
        # - file
        # - file
        in_rule_files = False
        in_re = re.compile(r"^rule_files:\s*$")
        array_element_re = re.compile(r"\s*-\s+(.+)$")

        for line in template.split("\n"):
            m = in_re.match(line)
            if m:
                in_rule_files = True
                continue

            if in_rule_files:
                m = array_element_re.match(line)
                if m:
                    rule_files.append(m.group(1))
                else:
                    break

    return rule_files


def check_prometheus_tests(tests, rules, thread_pool_size):
    """Returns a list of dicts with failed test runs. To make things (much)
    simpler we will allow only one prometheus rule per test as will need to run
    the tests per every appearance of the rule files in a namespace s rules can
    be templates. Rule tests need to be templated too using the same variables
    the original rule has as rule labels can have different values per
    namespace.
    """
    failed_tests = []

    # list of dicts containing tests to run
    # {'rule_files': {'path': 'contents'}
    #  'test': 'test content',
    #  'path': '/path/to/test/file',
    #  'namespace': 'namespace',
    #  'cluster': 'cluster'}
    tests_to_run = []

    for path, test in tests.items():
        test_to_run = {"path": path}

        rule_files = get_rule_files_from_jinja_test_template(test)
        if not rule_files:
            failed_tests.append({**test_to_run, "check_result": "Cannot parse test"})
            continue

        # this makes things so much simpler. Let's revisit it if we need
        if len(rule_files) > 1:
            failed_tests.append(
                {**test_to_run, "check_result": "Only 1 rule file per test"}
            )
            continue

        if rule_files[0] not in rules:
            msg = (
                f"rule file {rule_files[0]} does not exist or is not "
                "referenced in any namespace file"
            )
            failed_tests.append({**test_to_run, "check_result": msg})
            continue

        try:
            for cluster, namespaces in rules[rule_files[0]].items():
                for namespace, rule_data in namespaces.items():
                    variables = rule_data.get("variables", {})
                    test_yaml_spec = yaml.safe_load(
                        orb.process_extracurlyjinja2_template(body=test, vars=variables)
                    )
                    test_yaml_spec.pop("$schema")

                    tests_to_run.append(
                        {
                            **test_to_run,
                            "test": test_yaml_spec,
                            "rule_files": {rule_files[0]: rule_data["spec"]},
                            "namespace": namespace,
                            "cluster": cluster,
                        }
                    )
        except Exception as e:
            logging.warning(traceback.format_exc())
            msg = (
                f"Error in test template for cluster {cluster} and "
                f"namespace {namespace}: {e}"
            )
            failed_tests.append({**test_to_run, "check_result": msg})
            continue

    result = threaded.run(
        func=run_test, iterable=tests_to_run, thread_pool_size=thread_pool_size
    )

    failed_tests.extend([test for test in result if not test["check_result"]])

    return failed_tests


def run(dry_run, thread_pool_size=10, cluster_name=None):
    orb.QONTRACT_INTEGRATION = QONTRACT_INTEGRATION
    orb.QONTRACT_INTEGRATION_VERSION = QONTRACT_INTEGRATION_VERSION

    rules = get_prometheus_rules(cluster_name)
    invalid_rules = check_prometheus_rules(rules, thread_pool_size)
    if invalid_rules:
        for i in invalid_rules:
            logging.error(
                f"Error in rule {i['path']} from namespace "
                f"{i['namespace']} in cluster "
                f"{i['cluster']}:  {i['check_result']}"
            )

    tests = get_prometheus_tests()
    failed_tests = check_prometheus_tests(tests, rules, thread_pool_size)
    if failed_tests:
        for f in failed_tests:
            msg = f"Error in test {f['path']}"
            if "cluster" in f:
                msg += f" from namespace {f['namespace']} in cluster" f"{f['cluster']}"
            msg += f":  {f['check_result']}"

            logging.error(msg)

    if invalid_rules or failed_tests:
        sys.exit(ExitCodes.ERROR)
