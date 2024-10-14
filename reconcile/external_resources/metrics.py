from pydantic import BaseModel

from reconcile.external_resources.meta import QONTRACT_INTEGRATION
from reconcile.utils.metrics import (
    CounterMetric,
    GaugeMetric,
    normalize_integration_name,
)


class ExternalResourcesBaseMetric(BaseModel):
    integration = normalize_integration_name(QONTRACT_INTEGRATION)
    app: str
    environment: str
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


class ExternalResourcesResourceStatus(ExternalResourcesBaseMetric, GaugeMetric):
    status: str

    @classmethod
    def name(cls) -> str:
        return "external_resources_resource_status"
