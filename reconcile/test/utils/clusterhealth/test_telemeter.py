from collections.abc import Callable

import pytest

from reconcile.utils.clusterhealth.providerbase import ClusterHealth
from reconcile.utils.clusterhealth.telemeter import (
    PrometheusQuerier,
    TelemeterClusterHealthProvider,
)
from reconcile.utils.prometheus import PrometheusVector


@pytest.fixture
def telemeter_cluster_health_querier_builder() -> (
    Callable[[dict[str, list[str]]], PrometheusQuerier]
):
    def build(cluster_alerts: dict[str, list[str]]) -> PrometheusQuerier:
        class StubTelemeterClusterHealthQuerier(PrometheusQuerier):
            def instant_vector_query(self, query: str) -> list[PrometheusVector]:
                return [
                    PrometheusVector(
                        metric={
                            "__name__": "",
                            "_id": external_id,
                            "alertname": alertname,
                            "alertstate": "firing",
                            "severity": "critical",
                            "organization": "xxx",
                        },
                        value=(0.0, 1),
                    )
                    for external_id, critical_alerts in cluster_alerts.items()
                    for alertname in critical_alerts
                ]

        return StubTelemeterClusterHealthQuerier()

    return build


@pytest.fixture
def telemeter_health_provider(
    telemeter_cluster_health_querier_builder: Callable[
        [dict[str, list[str]]], PrometheusQuerier
    ],
) -> TelemeterClusterHealthProvider:
    return TelemeterClusterHealthProvider(
        telemeter_cluster_health_querier_builder({
            "cluster-uuid-1": [
                "SomethingSerious",
                "OmgOmgOmgAlert",
            ],
            "cluster-uuid-2": [
                "EverythingIsBroken",
            ],
        })
    )


def test_cluster_health_check_org(
    telemeter_health_provider: TelemeterClusterHealthProvider,
) -> None:
    result = telemeter_health_provider.cluster_health_for_org(
        org_id="org-id",
    )
    assert "cluster-uuid-1" in result
    assert set(result["cluster-uuid-1"].errors or []) == {
        "SomethingSerious",
        "OmgOmgOmgAlert",
    }
    assert "cluster-uuid-2" in result
    assert set(result["cluster-uuid-2"].errors or []) == {"EverythingIsBroken"}


def test_cluster_health_check_cluster(
    telemeter_health_provider: TelemeterClusterHealthProvider,
) -> None:
    result = telemeter_health_provider.cluster_health(
        cluster_external_id="cluster-uuid-1",
        org_id="org-id",
    )
    assert set(result.errors or []) == {
        "SomethingSerious",
        "OmgOmgOmgAlert",
    }

    result = telemeter_health_provider.cluster_health(
        cluster_external_id="cluster-uuid-2",
        org_id="org-id",
    )
    assert set(result.errors or []) == {"EverythingIsBroken"}


def test_cluster_health_check_cluster_not_found(
    telemeter_health_provider: TelemeterClusterHealthProvider,
) -> None:
    result = telemeter_health_provider.cluster_health(
        cluster_external_id="does-not-exist",
        org_id="org-id",
    )
    assert result == ClusterHealth(source="telemeter")
