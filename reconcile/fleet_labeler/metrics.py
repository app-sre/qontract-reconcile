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

    def set_managed_labels_gauge(
        self, ocm_name: str, spec_name: str, value: int
    ) -> None:
        metrics.set_gauge(
            FleetLabelerManagedLabelsGauge(
                ocm_name=ocm_name,
                spec=spec_name,
            ),
            value,
        )

    def set_managed_clusters_gauge(self, value: int) -> None:
        metrics.set_gauge(
            FleetLabelerManagedClustersGauge(),
            value,
        )


class FleetLabelerBaseMetric(BaseModel):
    integration: str = QONTRACT_INTEGRATION


class FleetLabelerSpecBaseMetric(FleetLabelerBaseMetric):
    ocm_name: str
    spec: str


class FleetLabelerDuplicateClusterMatchesGauge(FleetLabelerSpecBaseMetric, GaugeMetric):
    """
    Gauge for the number of clusters that have duplicate matches. Clusters with
    duplicate matches are being ignored by fleet labeler, as it cannot clearly
    determine which default label to apply for the cluster. Check the logs to
    identify the clusters with duplicate matches.
    """

    @classmethod
    def name(cls) -> str:
        return "fleet_labeler_duplicate_cluster_matches"


class FleetLabelerLabelRenderingErrorGauge(FleetLabelerSpecBaseMetric, GaugeMetric):
    """
    Gauge for the number of clusters that have label render errors. This
    happens when the fleet labeler is unable to render the subscription labels
    template for a cluster. Check the logs to identify the clusters with label render errors.
    """

    @classmethod
    def name(cls) -> str:
        return "fleet_labeler_label_rendering_error"


class FleetLabelerManagedLabelsGauge(FleetLabelerSpecBaseMetric, GaugeMetric):
    """
    Gauge for the current number of labels under management.
    Note, that label<->cluster combination must be unique across all
    specs, hence we can give the spec as a label here.
    """

    @classmethod
    def name(cls) -> str:
        return "fleet_labeler_managed_labels"


class FleetLabelerManagedClustersGauge(FleetLabelerBaseMetric, GaugeMetric):
    """
    Gauge for the current number of clusters under management.
    Note, that a cluster can be part of multiple spec inventories.
    This metric only cares about the total number of unique clusters,
    thus the spec is not a label here.
    """

    @classmethod
    def name(cls) -> str:
        return "fleet_labeler_managed_clusters"
