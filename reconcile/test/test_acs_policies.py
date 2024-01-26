import copy
from typing import Any
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture

from reconcile.acs_policies import AcsPoliciesIntegration
from reconcile.gql_definitions.acs.acs_policies import (
    AcsPolicyConditionsCveV1,
    AcsPolicyConditionsCvssV1,
    AcsPolicyConditionsSeverityV1,
    AcsPolicyQueryData,
    AcsPolicyScopeClusterV1,
    AcsPolicyScopeNamespaceV1,
    AcsPolicyV1,
    ClusterV1,
    NamespaceV1,
    NamespaceV1_ClusterV1,
)
from reconcile.utils.acs.policies import AcsPolicyApi, Policy, PolicyCondition, Scope

CLUSTER_NAME_ONE = "app-sre-stage"
CLUSTER_ID_ONE = "5211d395-5cf7-4185-a1fb-d88f41bc7542"
CLUSTER_NAME_TWO = "app-sre-prod"
CLUSTER_ID_TWO = "a217cca7-d85a-4be1-9703-f58866fdbe2d"
CUSTOM_POLICY_ONE_NAME = "app-sre-clusters-fixable-cve-7-fixable"
CUSTOM_POLICY_ONE_ID = "365d4e71-3241-4448-9f3d-eb0eed1c1820"
CUSTOM_POLICY_TWO_NAME = "app-sre-namespaces-severity-critical"
CUSTOM_POLICY_TWO_ID = "2200245e-b700-46c2-8793-3e437fca6aa0"
JIRA_NOTIFIER_NAME = "app-sre-jira"
JIRA_NOTIFIER_ID = "54170627-da34-40cb-839a-af9fbeac10fb"


@pytest.fixture
def query_data_desired_state() -> AcsPolicyQueryData:
    return AcsPolicyQueryData(
        acs_policies=[
            AcsPolicyV1(
                name=CUSTOM_POLICY_ONE_NAME,
                description="CVEs within app-sre clusters with CVSS score gte to 7 and fixable",
                severity="high",
                notifiers=[JIRA_NOTIFIER_NAME],
                categories=["vulnerability-management"],
                scope=AcsPolicyScopeClusterV1(
                    level="cluster",
                    clusters=[
                        ClusterV1(name=CLUSTER_NAME_ONE),
                        ClusterV1(name=CLUSTER_NAME_TWO),
                    ],
                ),
                conditions=[
                    AcsPolicyConditionsCvssV1(
                        policyField="cvss", comparison="gte", score=7
                    ),
                    AcsPolicyConditionsCveV1(policyField="cve", fixable=True),
                ],
            ),
            AcsPolicyV1(
                name=CUSTOM_POLICY_TWO_NAME,
                description="image security policy violations of critical severity within app-sre namespaces",
                severity="critical",
                notifiers=[],
                categories=["vulnerability-management", "devops-best-practices"],
                scope=AcsPolicyScopeNamespaceV1(
                    level="namespace",
                    namespaces=[
                        NamespaceV1(
                            name="app-interface-stage",
                            cluster=NamespaceV1_ClusterV1(name="app-sre-stage"),
                        ),
                        NamespaceV1(
                            name="app-interface-production",
                            cluster=NamespaceV1_ClusterV1(name="app-sre-prod"),
                        ),
                    ],
                ),
                conditions=[
                    AcsPolicyConditionsSeverityV1(
                        policyField="severity", comparison="eq", level="critical"
                    )
                ],
            ),
        ]
    )


@pytest.fixture
def modeled_acs_policies() -> list[Policy]:
    return [
        Policy(
            name=CUSTOM_POLICY_ONE_NAME,
            description="CVEs within app-sre clusters with CVSS score gte to 7 and fixable",
            severity="HIGH_SEVERITY",
            notifiers=[JIRA_NOTIFIER_ID],
            categories=["Vulnerability Management"],
            scope=[
                Scope(cluster=CLUSTER_ID_ONE, namespace=""),
                Scope(cluster=CLUSTER_ID_TWO, namespace=""),
            ],
            conditions=[
                PolicyCondition(field_name="CVSS", values=[">=7"], negate=False),
                PolicyCondition(field_name="Fixable", values=["true"], negate=False),
            ],
        ),
        Policy(
            name=CUSTOM_POLICY_TWO_NAME,
            description="image security policy violations of critical severity within app-sre namespaces",
            severity="CRITICAL_SEVERITY",
            notifiers=[],
            categories=["DevOps Best Practices", "Vulnerability Management"],
            scope=[
                Scope(cluster=CLUSTER_ID_ONE, namespace="app-interface-stage"),
                Scope(cluster=CLUSTER_ID_TWO, namespace="app-interface-production"),
            ],
            conditions=[
                PolicyCondition(
                    field_name="Severity", values=["CRITICAL"], negate=False
                )
            ],
        ),
    ]


@pytest.fixture
def api_response_policies_summary() -> Any:
    return {
        "policies": [
            {
                "id": CUSTOM_POLICY_ONE_ID,
                "name": CUSTOM_POLICY_ONE_NAME,
                "description": "CVEs within app-sre clusters with CVSS score gte to 7 and fixable",
                "severity": "HIGH_SEVERITY",
                "notifiers": [JIRA_NOTIFIER_ID],
                "disabled": False,
                "lifecycleStages": ["BUILD", "DEPLOY"],
                "lastUpdated": None,
                "eventSource": "NOT_APPLICABLE",
                "isDefault": False,
            },
            {
                "id": CUSTOM_POLICY_TWO_ID,
                "name": CUSTOM_POLICY_TWO_NAME,
                "description": "image security policy violations of critical severity within app-sre namespaces",
                "severity": "CRITICAL_SEVERITY",
                "disabled": False,
                "lifecycleStages": ["BUILD", "DEPLOY"],
                "notifiers": [],
                "lastUpdated": None,
                "eventSource": "NOT_APPLICABLE",
                "isDefault": False,
            },
            {
                "id": "1111245e-7700-46c2-8793-3e437fca6aa0",
                "name": "some-default-policy",
                "description": "default policy that should not be included in reconcile",
                "severity": "CRITICAL_SEVERITY",
                "disabled": False,
                "lifecycleStages": ["BUILD", "DEPLOY"],
                "notifiers": [],
                "lastUpdated": None,
                "eventSource": "NOT_APPLICABLE",
                "isDefault": True,
            },
        ]
    }


@pytest.fixture
def api_response_policies_specific() -> list[Any]:
    return [
        {
            "id": CUSTOM_POLICY_ONE_ID,
            "name": CUSTOM_POLICY_ONE_NAME,
            "description": "CVEs within app-sre clusters with CVSS score gte to 7 and fixable",
            "disabled": False,
            "categories": ["Vulnerability Management"],
            "lifecycleStages": ["BUILD", "DEPLOY"],
            "eventSource": "NOT_APPLICABLE",
            "exclusions": [],
            "scope": [
                {"cluster": CLUSTER_ID_ONE, "namespace": "", "label": None},
                {"cluster": CLUSTER_ID_TWO, "namespace": "", "label": None},
            ],
            "severity": "HIGH_SEVERITY",
            "enforcementActions": [],
            "notifiers": [JIRA_NOTIFIER_ID],
            "policySections": [
                {
                    "sectionName": "primary",
                    "policyGroups": [
                        {
                            "fieldName": "CVSS",
                            "booleanOperator": "OR",
                            "negate": False,
                            "values": [{"value": ">=7"}],
                        },
                        {
                            "fieldName": "Fixable",
                            "booleanOperator": "OR",
                            "negate": False,
                            "values": [{"value": "true"}],
                        },
                    ],
                }
            ],
            "mitreAttackVectors": [],
            "criteriaLocked": False,
            "mitreVectorsLocked": False,
            "isDefault": False,
        },
        {
            "id": CUSTOM_POLICY_TWO_ID,
            "name": CUSTOM_POLICY_TWO_NAME,
            "description": "image security policy violations of critical severity within app-sre namespaces",
            "disabled": False,
            "categories": ["Vulnerability Management", "DevOps Best Practices"],
            "lifecycleStages": ["BUILD", "DEPLOY"],
            "eventSource": "NOT_APPLICABLE",
            "exclusions": [],
            "scope": [
                {
                    "cluster": CLUSTER_ID_ONE,
                    "namespace": "app-interface-stage",
                    "label": None,
                },
                {
                    "cluster": CLUSTER_ID_TWO,
                    "namespace": "app-interface-production",
                    "label": None,
                },
            ],
            "severity": "CRITICAL_SEVERITY",
            "enforcementActions": [],
            "notifiers": [],
            "policySections": [
                {
                    "sectionName": "primary",
                    "policyGroups": [
                        {
                            "fieldName": "Severity",
                            "booleanOperator": "OR",
                            "negate": False,
                            "values": [{"value": "CRITICAL"}],
                        }
                    ],
                }
            ],
            "mitreAttackVectors": [],
            "criteriaLocked": False,
            "mitreVectorsLocked": False,
            "isDefault": False,
        },
    ]


@pytest.fixture
def api_response_list_notifiers() -> list[AcsPolicyApi.NotifierIdentifiers]:
    return [
        AcsPolicyApi.NotifierIdentifiers(id=JIRA_NOTIFIER_ID, name=JIRA_NOTIFIER_NAME)
    ]


@pytest.fixture
def api_response_list_clusters() -> list[AcsPolicyApi.ClusterIdentifiers]:
    return [
        AcsPolicyApi.ClusterIdentifiers(id=CLUSTER_ID_ONE, name=CLUSTER_NAME_ONE),
        AcsPolicyApi.ClusterIdentifiers(id=CLUSTER_ID_TWO, name=CLUSTER_NAME_TWO),
    ]


def test_get_desired_state(
    mocker: MockerFixture,
    query_data_desired_state: AcsPolicyQueryData,
    modeled_acs_policies: list[Policy],
    api_response_list_notifiers: list[AcsPolicyApi.NotifierIdentifiers],
    api_response_list_clusters: list[AcsPolicyApi.ClusterIdentifiers],
) -> None:
    query_func = mocker.patch(
        "reconcile.gql_definitions.acs.acs_policies.query", autospec=True
    )
    query_func.return_value = query_data_desired_state

    integration = AcsPoliciesIntegration()
    result = integration.get_desired_state(
        query_func=query_func,
        notifiers=api_response_list_notifiers,
        clusters=api_response_list_clusters,
    )
    assert result == modeled_acs_policies


def test_get_current_state(
    mocker: MockerFixture,
    modeled_acs_policies: list[Policy],
    api_response_policies_summary: list[Any],
    api_response_policies_specific: list[Any],
) -> None:
    list_custom_policies = Mock()
    list_custom_policies.json.return_value = api_response_policies_summary
    specific_custom_policy_1 = Mock()
    specific_custom_policy_1.json.return_value = api_response_policies_specific[0]
    specific_custom_policy_2 = Mock()
    specific_custom_policy_2.json.return_value = api_response_policies_specific[1]
    mocker.patch.object(
        AcsPolicyApi,
        "generic_request",
        side_effect=[
            list_custom_policies,
            specific_custom_policy_1,
            specific_custom_policy_2,
        ],
    )
    with AcsPolicyApi(instance={"url": "foo", "token": "bar"}) as acs:
        assert sorted(acs.get_custom_policies(), key=lambda p: p.name) == sorted(
            modeled_acs_policies, key=lambda p: p.name
        )


def test_create_policy(
    mocker: MockerFixture, modeled_acs_policies: list[Policy]
) -> None:
    dry_run = False
    desired = modeled_acs_policies
    current = modeled_acs_policies[:-1]

    acs_mock = Mock()
    mocker.patch.object(acs_mock, "create_or_update_policy")

    integration = AcsPoliciesIntegration()
    integration.reconcile(
        desired=desired, current=current, acs=acs_mock, dry_run=dry_run
    )

    acs_mock.create_or_update_policy.assert_has_calls([
        mocker.call(desired=modeled_acs_policies[1])
    ])


def test_create_policy_dry_run(
    mocker: MockerFixture, modeled_acs_policies: list[Policy]
) -> None:
    dry_run = True
    desired = modeled_acs_policies
    current = modeled_acs_policies[:-1]

    acs_mock = Mock()
    mocker.patch.object(acs_mock, "create_or_update_policy")

    integration = AcsPoliciesIntegration()
    integration.reconcile(
        desired=desired, current=current, acs=acs_mock, dry_run=dry_run
    )

    acs_mock.create_or_update_policy.assert_not_called()


def test_delete_policy(
    mocker: MockerFixture,
    modeled_acs_policies: list[Policy],
    api_response_policies_summary: Any,
) -> None:
    dry_run = False
    desired = modeled_acs_policies[:-1]
    current = modeled_acs_policies

    acs_mock = Mock()
    mocker.patch.object(acs_mock, "delete_policy")
    mocker.patch.object(
        acs_mock,
        "list_custom_policies",
        return_value=api_response_policies_summary["policies"][:-1],
    )

    integration = AcsPoliciesIntegration()
    integration.reconcile(
        desired=desired, current=current, acs=acs_mock, dry_run=dry_run
    )

    acs_mock.delete_policy.assert_has_calls([mocker.call(CUSTOM_POLICY_TWO_ID)])


def test_delete_policy_dry_run(
    mocker: MockerFixture,
    modeled_acs_policies: list[Policy],
    api_response_policies_summary: Any,
) -> None:
    dry_run = True
    desired = modeled_acs_policies[:-1]
    current = modeled_acs_policies

    acs_mock = Mock()
    mocker.patch.object(acs_mock, "delete_policy")
    mocker.patch.object(
        acs_mock,
        "list_custom_policies",
        return_value=api_response_policies_summary["policies"][:-1],
    )

    integration = AcsPoliciesIntegration()
    integration.reconcile(
        desired=desired, current=current, acs=acs_mock, dry_run=dry_run
    )

    acs_mock.delete_policy.assert_not_called()


def test_update_policy(
    mocker: MockerFixture,
    modeled_acs_policies: list[Policy],
    api_response_policies_summary: Any,
) -> None:
    dry_run = False
    desired = modeled_acs_policies
    current = copy.deepcopy(modeled_acs_policies)
    current[0].severity = "LOW_SEVERITY"

    acs_mock = Mock()
    mocker.patch.object(acs_mock, "create_or_update_policy")
    mocker.patch.object(
        acs_mock,
        "list_custom_policies",
        return_value=api_response_policies_summary["policies"],
    )

    integration = AcsPoliciesIntegration()
    integration.reconcile(
        desired=desired, current=current, acs=acs_mock, dry_run=dry_run
    )

    acs_mock.create_or_update_policy.assert_has_calls([
        mocker.call(desired=desired[0], id=CUSTOM_POLICY_ONE_ID)
    ])


def test_update_policy_dry_run(
    mocker: MockerFixture,
    modeled_acs_policies: list[Policy],
    api_response_policies_summary: Any,
) -> None:
    dry_run = True
    desired = modeled_acs_policies
    current = copy.deepcopy(modeled_acs_policies)
    current[0].severity = "LOW_SEVERITY"

    acs_mock = Mock()
    mocker.patch.object(acs_mock, "create_or_update_policy")
    mocker.patch.object(
        acs_mock,
        "list_custom_policies",
        return_value=api_response_policies_summary["policies"],
    )

    integration = AcsPoliciesIntegration()
    integration.reconcile(
        desired=desired, current=current, acs=acs_mock, dry_run=dry_run
    )

    acs_mock.create_or_update_policy.assert_not_called()
