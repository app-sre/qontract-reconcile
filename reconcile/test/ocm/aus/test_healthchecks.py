import pytest

from reconcile.aus.healthchecks import (
    AUSClusterHealthCheckProvider,
    build_cluster_health_providers_for_organization,
)
from reconcile.test.ocm.aus.fixtures import build_organization
from reconcile.utils.clusterhealth.providerbase import (
    ClusterHealth,
    ClusterHealthProvider,
    EmptyClusterHealthProvider,
)


@pytest.mark.parametrize(
    "org_providers",
    [
        [
            ("provider-a", True),
        ],
        [
            ("provider-a", True),
            ("provider-b", False),
        ],
    ],
)
def test_build_cluster_health_providers_for_organization_filtering(
    org_providers: list[tuple[str, bool]],
) -> None:
    org = build_organization(health_checks=org_providers)
    health_check_provider = build_cluster_health_providers_for_organization(
        org=org,
        providers={
            "provider-a": EmptyClusterHealthProvider(),
            "provider-b": EmptyClusterHealthProvider(),
            "provider-c": EmptyClusterHealthProvider(),
        },
    )

    assert {
        (provider, enforced)
        for provider, (_, enforced) in health_check_provider.providers.items()
    } == set(org_providers)


def test_build_cluster_health_providers_for_organization_not_existing() -> None:
    org = build_organization(
        health_checks=[
            ("provider-d", True),
        ]
    )
    with pytest.raises(Exception):
        build_cluster_health_providers_for_organization(
            org=org,
            providers={
                "provider-a": EmptyClusterHealthProvider(),
                "provider-b": EmptyClusterHealthProvider(),
                "provider-c": EmptyClusterHealthProvider(),
            },
        )


class MockProvider(ClusterHealthProvider):
    def __init__(self, source: str, results: dict[tuple[str, str], ClusterHealth]):
        self.source = source
        self.results = results

    def cluster_health(self, cluster_external_id: str, org_id: str) -> ClusterHealth:
        return self.results.get((
            cluster_external_id,
            org_id,
        )) or ClusterHealth(source=self.source)


@pytest.fixture
def health_check_provider() -> AUSClusterHealthCheckProvider:
    return (
        AUSClusterHealthCheckProvider()
        .add_provider(
            "provider-a",
            MockProvider(
                source="provider-a",
                results={
                    ("cluster-uuid-1", "org-id"): ClusterHealth(
                        source="provider-a", errors={"error-a"}
                    ),
                    ("cluster-uuid-2", "org-id"): ClusterHealth(source="provider-a"),
                },
            ),
            True,
        )
        .add_provider(
            "provider-b",
            MockProvider(
                source="provider-b",
                results={
                    ("cluster-uuid-1", "org-id"): ClusterHealth(
                        source="provider-b", errors={"error-b"}
                    ),
                    ("cluster-uuid-2", "org-id"): ClusterHealth(source="provider-b"),
                    ("cluster-uuid-3", "org-id"): ClusterHealth(
                        source="provider-b", errors={"error-b"}
                    ),
                },
            ),
            False,
        )
    )


@pytest.mark.parametrize(
    "cluster_uuid_id,has_errors,has_enforced_errors,errors",
    [
        (
            "cluster-uuid-1",
            True,
            True,
            {
                ("provider-a", "error-a", True),
                ("provider-b", "error-b", False),
            },
        ),
        (
            "cluster-uuid-2",
            False,
            False,
            set(),
        ),
        (
            "cluster-uuid-3",
            True,
            False,
            {
                ("provider-b", "error-b", False),
            },
        ),
    ],
)
def test_cluster_health_aggregation(
    cluster_uuid_id: str,
    has_errors: bool,
    has_enforced_errors: bool,
    errors: set[tuple[str, str, bool]],
    health_check_provider: AUSClusterHealthCheckProvider,
) -> None:
    result = health_check_provider.cluster_health(cluster_uuid_id, "org-id")
    assert result.has_health_errors() == has_errors
    assert result.has_health_errors(only_enforced=True) == has_enforced_errors
    assert {
        (
            e.source,
            e.error,
            e.enforce,
        )
        for e in result.get_errors()
    } == errors
