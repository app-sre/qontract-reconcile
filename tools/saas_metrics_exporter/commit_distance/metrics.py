from pydantic import BaseModel

from reconcile.utils.metrics import (
    GaugeMetric,
)


class SaasBaseMetric(BaseModel):
    "Base class for Saas metrics"

    integration: str = "saas_metrics_exporter"


class SaasCommitDistanceGauge(SaasBaseMetric, GaugeMetric):
    "Gauge for the commit distance between saas targets in a channel"

    channel: str
    publisher: str
    publisher_namespace: str
    subscriber: str
    subscriber_namespace: str
    app: str

    @classmethod
    def name(cls) -> str:
        return "commit_distance"
