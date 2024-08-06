from pydantic import BaseModel

from reconcile.utils.metrics import (
    CounterMetric,
    ErrorRateMetricSet,
    GaugeMetric,
)


class DTPBaseMetric(BaseModel):
    integration: str
    ocm_env: str


class DTPOrganizationReconcileCounter(DTPBaseMetric, CounterMetric):
    org_id: str

    @classmethod
    def name(cls) -> str:
        return "dtp_organization_reconciled"


class DTPOrganizationReconcileErrorCounter(DTPBaseMetric, CounterMetric):
    org_id: str

    @classmethod
    def name(cls) -> str:
        return "dtp_organization_reconcile_errors"


class DTPOrganizationErrorRate(ErrorRateMetricSet):
    def __init__(self, integration: str, org_id: str, ocm_env: str) -> None:
        super().__init__(
            counter=DTPOrganizationReconcileCounter(
                integration=integration,
                ocm_env=ocm_env,
                org_id=org_id,
            ),
            error_counter=DTPOrganizationReconcileErrorCounter(
                integration=integration,
                ocm_env=ocm_env,
                org_id=org_id,
            ),
        )


class DTPClustersManagedGauge(DTPBaseMetric, GaugeMetric):
    "Gauge for the number of clusters DTP manages"

    @classmethod
    def name(cls) -> str:
        return "dtp_clusters_managed"


class DTPTokensManagedGauge(DTPBaseMetric, GaugeMetric):
    "Gauge for the number of tokens DTP manages"

    dt_tenant_id: str

    @classmethod
    def name(cls) -> str:
        return "dtp_tokens_managed"
