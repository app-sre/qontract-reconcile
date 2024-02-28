import json
import logging
import sys
from collections import defaultdict
from collections.abc import (
    Iterable,
    Mapping,
)
from typing import (
    Any,
    Optional,
)

import yaml
from deepdiff import DeepHash
from pydantic import BaseModel
from sretoolbox.utils import threaded

import reconcile.openshift_resources_base as orb
from reconcile.gql_definitions.common.app_interface_vault_settings import (
    AppInterfaceSettingsV1,
)
from reconcile.status import ExitCodes
from reconcile.typed_queries.alerting_services_settings import get_alerting_services
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils import (
    gql,
    promtool,
)
from reconcile.utils.jinja2.utils import process_extracurlyjinja2_template
from reconcile.utils.runtime.integration import DesiredStateShardConfig
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.structs import CommandExecutionResult

# This comes from prometheus-operator. It is the largest configmap that they will
# create. It is also the largest PrometheusRule yaml file they will process to add it
# to the configmap.
MAX_CONFIGMAP_SIZE = 0.5 * 1024 * 1024

QONTRACT_INTEGRATION = "prometheus_rules_tester"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)

PROVIDERS = ["prometheus-rule"]

NAMESPACE_NAME = "openshift-customer-monitoring"


class TestContent(BaseModel):
    test_path: str
    test: dict


class Test(BaseModel):
    cluster_name: str
    namespace_name: str
    rule_path: str
    rule: dict
    rule_length: int
    tests: Optional[list[TestContent]]
    result: Optional[CommandExecutionResult] = None


class RuleToFetch(BaseModel):
    namespace: dict[str, Any]
    resource: dict[str, Any]


def fetch_rule_and_tests(
    rule: RuleToFetch, vault_settings: AppInterfaceSettingsV1
) -> Test:
    """Fetches associated data from a rule and builds a Test object"""
    if "add_path_to_prom_rules" not in rule.resource:
        rule.resource["add_path_to_prom_rules"] = False

    openshift_resource = orb.fetch_openshift_resource(
        resource=rule.resource,
        parent=rule.namespace,
        settings=vault_settings.dict(by_alias=True),
    )

    rule_body = openshift_resource.body
    rule_length = len(yaml.dump(rule_body))  # Same as prometheus-operator does it.

    if rule.resource["type"] == "resource-template-extracurlyjinja2":
        variables = json.loads(rule.resource.get("variables") or "{}")
        variables["resource"] = rule.resource

    tests: list[TestContent] = []
    for test_path in rule.resource.get("tests") or []:
        test_raw_yaml = gql.get_resource(test_path)["content"]

        if rule.resource["type"] == "resource-template-extracurlyjinja2":
            test_raw_yaml = process_extracurlyjinja2_template(
                body=test_raw_yaml,
                vars=variables,
                settings=vault_settings.dict(by_alias=True),
            )

        test_yaml_spec = yaml.safe_load(test_raw_yaml)
        test_yaml_spec.pop("$schema")
        test_yaml_spec.pop("target_clusters", None)

        tests.append(
            TestContent(
                test_path=test_path,
                test=test_yaml_spec,
            )
        )

    return Test(
        cluster_name=rule.namespace["cluster"]["name"],
        namespace_name=rule.namespace["name"],
        rule_path=rule.resource["resource"]["path"],
        rule=rule_body,
        rule_length=rule_length,
        tests=tests,
    )


def get_rules_and_tests(
    vault_settings: AppInterfaceSettingsV1,
    thread_pool_size: int,
    cluster_name: Optional[str] = None,
) -> list[Test]:
    """Iterates through all namespaces and returns a list of tests to run"""
    namespace_with_prom_rules, _ = orb.get_namespaces(
        PROVIDERS,
        cluster_names=[cluster_name] if cluster_name else [],
        namespace_name=NAMESPACE_NAME,
    )

    iterable = []
    for namespace in namespace_with_prom_rules:
        prom_rules = [
            r for r in namespace["openshiftResources"] if r["provider"] in PROVIDERS
        ]
        for resource in prom_rules:
            iterable.append(
                RuleToFetch(
                    namespace=namespace,
                    resource=resource,
                )
            )

    return threaded.run(
        func=fetch_rule_and_tests,
        iterable=iterable,
        thread_pool_size=thread_pool_size,
        vault_settings=vault_settings,
    )


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
def check_valid_services(
    rule: Mapping, alerting_services: Iterable[str]
) -> CommandExecutionResult:
    """Check that all services in Prometheus rules are known.
    This replaces an enum in the json schema with a list
    in app-interface settings."""
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
            if service not in alerting_services:
                missing_services.add(service)

    if missing_services:
        return CommandExecutionResult(
            False, f"services are missing from alertingServices: {missing_services}"
        )

    return CommandExecutionResult(True, "")


# We return here a CommandExecutionResult as it is what run_test function has to
# add to the "result" field.
def check_rule_length(rule_length: int) -> CommandExecutionResult:
    """Checks rule length so that prom operator has no issues with it"""
    if rule_length > MAX_CONFIGMAP_SIZE:
        return CommandExecutionResult(
            False, f"Rules spec is larger than {MAX_CONFIGMAP_SIZE} bytes."
        )
    return CommandExecutionResult(True, "")


def run_test(test: Test, alerting_services: Iterable[str]) -> None:
    """Checks rules, run tests and stores the result in test.result"""
    check_rule_result = promtool.check_rule(test.rule["spec"])
    valid_services_result = check_valid_services(test.rule, alerting_services)
    rule_length_result = check_rule_length(test.rule_length)
    test.result = check_rule_result and valid_services_result and rule_length_result

    if not test.result:
        return

    rule_files = {test.rule_path: test.rule["spec"]}
    for t in test.tests or []:
        result = promtool.run_test(t.test, rule_files)
        test.result = test.result and result


def check_rules_and_tests(
    vault_settings: AppInterfaceSettingsV1,
    alerting_services: Iterable[str],
    thread_pool_size: int,
    cluster_name: Optional[str] = None,
) -> list[Test]:
    """Fetch rules and associated tests, run checks on rules and tests if they exist
    and return a list of failed checks/tests"""
    tests = get_rules_and_tests(
        vault_settings=vault_settings,
        thread_pool_size=thread_pool_size,
        cluster_name=cluster_name,
    )
    threaded.run(
        func=run_test,
        iterable=tests,
        thread_pool_size=thread_pool_size,
        alerting_services=alerting_services,
    )

    failed_tests = [test for test in tests if not test.result]

    return failed_tests


def run(
    dry_run: bool, thread_pool_size: int, cluster_name: Optional[str] = None
) -> None:
    """Check prometheus rules syntax and run the tests associated to them"""
    orb.QONTRACT_INTEGRATION = QONTRACT_INTEGRATION
    orb.QONTRACT_INTEGRATION_VERSION = QONTRACT_INTEGRATION_VERSION

    failed_tests = check_rules_and_tests(
        cluster_name=cluster_name,
        vault_settings=get_app_interface_vault_settings(),
        alerting_services=get_alerting_services(),
        thread_pool_size=thread_pool_size,
    )
    if failed_tests:
        for ft in failed_tests:
            logging.error(
                f"Error checking rule {ft.rule_path} from namespace {ft.namespace_name} in "
                f"cluster {ft.cluster_name}: {ft.result}"
            )

        sys.exit(ExitCodes.ERROR)


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    # early_exit doesn't support dataclasses or BaseModels yet, hence we have to store dicts
    with orb.early_exit_monkey_patch():
        state_for_clusters = defaultdict(list)
        tests = get_rules_and_tests(
            vault_settings=get_app_interface_vault_settings(),
            thread_pool_size=10,
        )
        for t in tests:
            state_for_clusters[t.cluster_name].append(t)

        state = {
            "state": {
                cluster: {"shard": cluster, "hash": DeepHash(state).get(state)}
                for cluster, state in state_for_clusters.items()
            }
        }

    return state


def desired_state_shard_config() -> DesiredStateShardConfig:
    return DesiredStateShardConfig(
        shard_arg_name="cluster_name",
        shard_path_selectors={"state.*.shard"},
        sharded_run_review=lambda proposal: len(proposal.proposed_shards) <= 4,
    )
