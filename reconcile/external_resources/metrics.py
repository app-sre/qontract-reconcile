from pydantic import BaseModel

from reconcile.utils.metrics import CounterMetric, GaugeMetric


class ExternalResourcesBaseMetric(BaseModel):
    integration = "external_resources"
    provision_provider: str
    provisioner_name: str
    provider: str
    identifier: str
    job_name: str


class ExternalResourcesReconcileErrorsCounter(
    ExternalResourcesBaseMetric, CounterMetric
):
    @classmethod
    def name(cls) -> str:
        return "external_resources_reconcile_errors"


class ExternalResourcesReconcileTimeGauge(ExternalResourcesBaseMetric, GaugeMetric):
    @classmethod
    def name(cls) -> str:
        return "external_resources_reconcile_time"
