from typing import Optional

from pydantic import BaseModel

from reconcile.typed_queries.clusters import get_clusters
from reconcile.utils import metrics
from reconcile.utils.metrics import GaugeMetric


class OverviewBaseMetric(BaseModel):
    "Base class for overview metrics"

    integration: str


class OverviewClustersGauge(OverviewBaseMetric, GaugeMetric):
    "Overview of clusters"

    @classmethod
    def name(cls) -> str:
        return "overview_clusters"


QONTRACT_INTEGRATION = "overview-metrics-exporter"


def run(dry_run: Optional[bool]):
    clusters = get_clusters()
    metrics.set_gauge(
        OverviewClustersGauge(
            integration=QONTRACT_INTEGRATION,
        ),
        len(clusters),
    )
