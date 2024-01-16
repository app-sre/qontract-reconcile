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
from reconcile.utils.acs.policies import Policy, PolicyCondition, Scope


@pytest.fixture
def query_data_desired_state() -> AcsPolicyQueryData:
    return AcsPolicyQueryData(
        acs_policies=[
            AcsPolicyV1(
                name="app-sre-clusters-fixable-cve-7-fixable",
                description="CVEs within app-sre clusters with CVSS score gte to 7 and fixable",
                severity="high",
                categories=["vulnerability-management"],
                scope=AcsPolicyScopeClusterV1(
                    level="cluster",
                    clusters=[
                        ClusterV1(name="app-sre-stage"),
                        ClusterV1(name="app-sre-prod"),
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
                name="app-sre-namespaces-severity-critical",
                description="image security policy violations of critical severity within app-sre namespaces",
                severity="critical",
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
            name="app-sre-clusters-fixable-cve-7-fixable",
            description="CVEs within app-sre clusters with CVSS score gte to 7 and fixable",
            severity="HIGH_SEVERITY",
            categories=["Vulnerability Management"],
            scope=[
                Scope(cluster="app-sre-prod", namespace=""),
                Scope(cluster="app-sre-stage", namespace=""),
            ],
            conditions=[
                PolicyCondition(field_name="CVSS", values=[">=7"], negate=False),
                PolicyCondition(field_name="Fixable", values=["true"], negate=False),
            ],
        ),
        Policy(
            name="app-sre-namespaces-severity-critical",
            description="image security policy violations of critical severity within app-sre namespaces",
            severity="CRITICAL_SEVERITY",
            categories=["DevOps Best Practices", "Vulnerability Management"],
            scope=[
                Scope(cluster="app-sre-prod", namespace="app-interface-production"),
                Scope(cluster="app-sre-stage", namespace="app-interface-stage"),
            ],
            conditions=[
                PolicyCondition(
                    field_name="Severity", values=["CRITICAL"], negate=False
                )
            ],
        ),
    ]


def test_get_desired_state(
    mocker: MockerFixture,
    query_data_desired_state: AcsPolicyQueryData,
    modeled_acs_policies: list[Policy],
) -> None:
    query_func = mocker.patch(
        "reconcile.gql_definitions.acs.acs_policies.query", autospec=True
    )
    query_func.return_value = query_data_desired_state

    integration = AcsPoliciesIntegration()
    result = integration.get_desired_state(query_func)

    print("RESULT")
    print(result)
    assert result == modeled_acs_policies


def test_get_current_state() -> None:
    pass
