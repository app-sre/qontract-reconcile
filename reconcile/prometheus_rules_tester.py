import json
import logging
import re
import sys
import traceback
from collections.abc import (
    Iterable,
    Mapping,
    MutableMapping,
)
from typing import (
    Any,
    Optional,
)

import yaml
from sretoolbox.utils import threaded

import reconcile.openshift_resources_base as orb
from reconcile import queries
from reconcile.status import ExitCodes
from reconcile.utils import (
    gql,
    promtool,
)
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.structs import CommandExecutionResult

# This comes from prometheus-operator. It is the largest configmap that they will
# create. It is also the largest PrometheusRule yaml file they will process to add it
# to the configmap.
MAX_CONFIGMAP_SIZE = 0.5 * 1024 * 1024

QONTRACT_INTEGRATION = "prometheus_rules_tester"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)

PROVIDERS = ["resource", "resource-template"]

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

PrometheusTests = dict[str, str]
PrometheusRules = dict[str, dict[str, dict[str, Any]]]


def get_prometheus_tests() -> PrometheusTests:
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
def get_prometheus_rules(
    cluster_name: Optional[str], settings: Mapping
) -> PrometheusRules:
    """Returns a dict of dicts indexed by path with rule data"""
    rules: PrometheusRules = {}
    namespaces_with_prom_rules, _ = orb.get_namespaces(
        PROVIDERS, resource_schema_filter="/openshift/prometheus-rule-1.yml"
    )
    for n in namespaces_with_prom_rules:
        namespace = n["name"]
        cluster = n["cluster"]["name"]

        if cluster_name and cluster != cluster_name:
            continue

        if (
            not n.get("managedResourceTypes")
            or "PrometheusRule" not in n["managedResourceTypes"]
        ):
            continue

        openshift_resources = n.get("openshiftResources")
        if not openshift_resources:
            logging.warning(
                "No openshiftResources defined for namespace "
                f"{namespace} in cluster {cluster}"
            )
            continue

        for r in openshift_resources:
            path = r["resource"]["path"]
            if path not in rules:
                rules[path] = {}

            # Or we will get an unexepected and confusing html_url annotation
            if "add_path_to_prom_rules" not in r:
                r["add_path_to_prom_rules"] = False

            openshift_resource = orb.fetch_openshift_resource(
                resource=r, parent=n, settings=settings
            )

            if cluster not in rules[path]:
                rules[path][cluster] = {}

            rule = openshift_resource.body
            rule_length = len(yaml.dump(rule))  # Same as prometheus-operator does it.
            rules[path][cluster][namespace] = {
                "spec": rule["spec"],
                "length": rule_length,
            }

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
def check_valid_services(rule: Mapping, settings: Mapping) -> CommandExecutionResult:
    """Check that all services in Prometheus rules are known.
    This replaces an enum in the json schema with a list
    in app-interface settings."""
    allowed_services = settings["alertingServices"]
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


# We return here a CommandExecutionResult as it is what check_rule function has to
# add to the "check_result" field.
def check_rule_length(rule_length: int) -> CommandExecutionResult:
    if rule_length > MAX_CONFIGMAP_SIZE:
        return CommandExecutionResult(
            False, f"Rules spec is larger than {MAX_CONFIGMAP_SIZE} bytes."
        )
    return CommandExecutionResult(True, "")


def check_rule(rule: MutableMapping, settings: Mapping) -> MutableMapping:
    promtool_check_result = promtool.check_rule(yaml_spec=rule["spec"])
    valid_services_result = check_valid_services(rule, settings)
    rule_length_result = check_rule_length(rule["length"])
    rule["check_result"] = (
        promtool_check_result and valid_services_result and rule_length_result
    )
    return rule


def check_prometheus_rules(
    rules: PrometheusRules, thread_pool_size: int, settings: Mapping
) -> list[dict[str, str]]:
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
                        "length": rule_data["length"],
                    }
                )

    result = threaded.run(
        func=check_rule,
        iterable=rules_to_check,
        thread_pool_size=thread_pool_size,
        settings=settings,
    )

    # return invalid rules
    return [rule for rule in result if not rule["check_result"]]


def run_test(test: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    test["check_result"] = promtool.run_test(
        test_yaml_spec=test["test"], rule_files=test["rule_files"]
    )
    return test


def get_data_from_jinja_test_template(
    template: str, desired_lists: list[str]
) -> dict[str, Any]:

    # Sort the list to allow the comparison with parsed_lists later
    desired_lists.sort()
    data: dict[str, Any] = {}

    try:
        parsed = yaml.safe_load(template)
        data = {k: parsed.get(k, []) for k in desired_lists}
        return data

    except Exception:
        # The jinja template is not valid yaml :(
        # A poor man's approach is used to get the required data
        # Let's assume people will follow the examples and use yaml lists as:
        # rule_files:
        # - file
        # - file
        data = {k: [] for k in desired_lists}
        parsed_lists = []
        list_element_re = re.compile(r"\s*-\s+(.+)$")
        root_attr_re = re.compile(r"^([a-z_]+):\s*$")

        target = ""
        in_list = False
        for line in template.split("\n"):
            if in_list:
                m = list_element_re.match(line)
                if m:
                    data[target].append(m.group(1))
                    continue
                else:
                    in_list = False
                    parsed_lists.append(target)
                    parsed_lists.sort()
                    if parsed_lists == desired_lists:
                        break

            m = root_attr_re.match(line)
            if m:
                attr = m.group(1)
                if attr in desired_lists:
                    target = attr
                    in_list = True
    return data


def check_prometheus_tests(
    tests: PrometheusTests,
    rules: PrometheusRules,
    clusters: Iterable[str],
    thread_pool_size: int,
    settings: Mapping,
) -> list[dict[str, Any]]:
    """Returns a list of dicts with failed test runs. To make things (much)
    simpler we will allow only one prometheus rule per test as will need to run
    the tests per every appearance of the rule files in a namespace s rules can
    be templates. Rule tests need to be templated too using the same variables
    the original rule has as rule labels can have different values per
    namespace.
    """
    failed_tests: list[dict[str, Any]] = []

    # list of dicts containing tests to run
    # {'rule_files': {'path': 'contents'}
    #  'test': 'test content',
    #  'path': '/path/to/test/file',
    #  'namespace': 'namespace',
    #  'cluster': 'cluster'}
    tests_to_run = []

    for path, test in tests.items():
        test_to_run = {"path": path}

        data = get_data_from_jinja_test_template(
            test, ["rule_files", "target_clusters"]
        )
        target_clusters = data["target_clusters"]
        rule_files = data["rule_files"]

        non_existing_target_clusters = [c for c in target_clusters if c not in clusters]
        if len(non_existing_target_clusters) > 0:
            failed_tests.append(
                {
                    **test_to_run,
                    "check_result": f"There are non-existing clusters in the target_clusters list: {non_existing_target_clusters}",
                }
            )
            continue

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
                if len(target_clusters) > 0 and cluster not in target_clusters:
                    logging.debug(
                        f"Skipping test {path} in cluster: {cluster}, cluster is not in the test target_clusters"
                    )
                    continue
                for namespace, rule_data in namespaces.items():
                    variables = rule_data.get("variables", {})
                    test_yaml_spec = yaml.safe_load(
                        orb.process_extracurlyjinja2_template(
                            body=test, vars=variables, settings=settings
                        )
                    )
                    test_yaml_spec.pop("$schema")
                    test_yaml_spec.pop("target_clusters", None)

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


def run(
    dry_run: bool, thread_pool_size: int = 10, cluster_name: Optional[str] = None
) -> None:
    orb.QONTRACT_INTEGRATION = QONTRACT_INTEGRATION
    orb.QONTRACT_INTEGRATION_VERSION = QONTRACT_INTEGRATION_VERSION

    settings = queries.get_app_interface_settings()

    rules = get_prometheus_rules(cluster_name, settings)
    invalid_rules = check_prometheus_rules(rules, thread_pool_size, settings)
    if invalid_rules:
        for i in invalid_rules:
            logging.error(
                f"Error in rule {i['path']} from namespace "
                f"{i['namespace']} in cluster "
                f"{i['cluster']}:  {i['check_result']}"
            )

    clusters = [c["name"] for c in queries.get_clusters(minimal=True)]
    tests = get_prometheus_tests()
    failed_tests = check_prometheus_tests(
        tests, rules, clusters, thread_pool_size, settings
    )
    if failed_tests:
        for f in failed_tests:
            msg = f"Error in test {f['path']}"
            if "cluster" in f:
                msg += f" from namespace {f['namespace']} in cluster" f"{f['cluster']}"
            msg += f":  {f['check_result']}"

            logging.error(msg)

    if invalid_rules or failed_tests:
        sys.exit(ExitCodes.ERROR)


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    state = orb.early_exit_desired_state(
        PROVIDERS, resource_schema_filter="/openshift/prometheus-rule-1.yml"
    )
    state["tests"] = get_prometheus_tests()
    return state
