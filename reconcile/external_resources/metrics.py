from pydantic import BaseModel

from reconcile.utils.metrics import (
    GaugeMetric,
)


class ExternalResourcesBaseMetric(BaseModel):
    integration = "external_resources"


class ExternalResourcesReconcileErrorsGauge(ExternalResourcesBaseMetric, GaugeMetric):
    provision_provider: str
    provisioner_name: str
    provider: str
    identifier: str

    @classmethod
    def name(cls) -> str:
        return "external_resources_reconcile_status"
