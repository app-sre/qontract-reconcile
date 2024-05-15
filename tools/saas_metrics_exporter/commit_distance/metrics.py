from reconcile.utils.metrics import (
    GaugeMetric,
)


class SaasCommitDistanceGauge(GaugeMetric):
    "Gauge for the commit distance between saas targets in a channel"

    integration: str = "saas_metrics_exporter"
    channel: str
    publisher: str
    publisher_namespace: str
    subscriber: str
    subscriber_namespace: str
    app: str

    @classmethod
    def name(cls) -> str:
        return "commit_distance"
