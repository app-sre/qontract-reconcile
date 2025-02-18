from pydantic import BaseModel

from reconcile.utils.metrics import (
    GaugeMetric,
)


class FleetLabelerBaseMetric(BaseModel):
    integration: str
    ocm_name: str


class FleetLabelerDuplicateClusterMatchesGauge(FleetLabelerBaseMetric, GaugeMetric):
    """
    Gauge for the number of clusters that have duplicate matches. Clusters with
    duplicate matches are being ignored by fleet labeler, as it cannot clearly
    determine which default label to apply for the cluster. Check the logs to
    identify the clusters with duplicate matches.
    """

    @classmethod
    def name(cls) -> str:
        return "fleet_labeler_duplicate_cluster_matches"
