from pydantic import BaseModel

from reconcile.fleet_labeler.meta import QONTRACT_INTEGRATION
from reconcile.utils import (
    metrics,
)
from reconcile.utils.metrics import (
    GaugeMetric,
)


class FleetLabelerMetrics:
    """
    Thin OOP wrapper for tests
    """

    def set_label_rendering_error_gauge(
        self, ocm_name: str, spec_name: str, value: int
    ) -> None:
        metrics.set_gauge(
            FleetLabelerDuplicateClusterMatchesGauge(
                ocm_name=ocm_name,
                spec=spec_name,
            ),
            value,
        )

    def set_duplicate_cluster_matches_gauge(
        self, ocm_name: str, spec_name: str, value: int
    ) -> None:
        metrics.set_gauge(
            FleetLabelerLabelRenderingErrorGauge(
                ocm_name=ocm_name,
                spec=spec_name,
            ),
            value,
        )


class FleetLabelerBaseMetric(BaseModel):
    integration: str = QONTRACT_INTEGRATION
    ocm_name: str
    spec: str


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


class FleetLabelerLabelRenderingErrorGauge(FleetLabelerBaseMetric, GaugeMetric):
    """
    Gauge for the number of clusters that have label render errors. This
    happens when the fleet labeler is unable to render the subscription labels
    template for a cluster. Check the logs to identify the clusters with label render errors.
    """

    @classmethod
    def name(cls) -> str:
        return "fleet_labeler_label_rendering_error"
