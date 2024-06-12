from functools import cache

from reconcile.utils.clusterhealth.providerbase import (
    ClusterHealth,
    ClusterHealthProvider,
)
from reconcile.utils.grouping import group_by
from reconcile.utils.prometheus import PrometheusQuerier

TELEMETER_SOURCE = "telemeter"


class TelemeterClusterHealthProvider(ClusterHealthProvider):
    def __init__(self, querier: PrometheusQuerier):
        self.querier = querier

    @cache
    def cluster_health_for_org(self, org_id: str) -> dict[str, ClusterHealth]:
        vectors_by_cluster = group_by(
            self.querier.instant_vector_query(telemeter_alert_query(org_id)),
            lambda v: v.mandatory_label("_id"),
        )
        return {
            cluster_id: ClusterHealth(
                errors={alert.mandatory_label("alertname") for alert in vectors},
                source=TELEMETER_SOURCE,
            )
            for cluster_id, vectors in vectors_by_cluster.items()
        }

    def cluster_health(self, cluster_external_id: str, org_id: str) -> ClusterHealth:
        health = self.cluster_health_for_org(org_id=org_id).get(cluster_external_id)
        return health or ClusterHealth(source=TELEMETER_SOURCE)


def telemeter_alert_query(organization_id: str) -> str:
    return f'alerts{{alertstate="firing", severity="critical"}} * on (_id) group_left(organization) max(ocm_subscription{{organization="{organization_id}"}}) by (_id, organization)'
