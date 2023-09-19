from pydantic import BaseModel

from reconcile.utils.metrics import (
    CounterMetric,
    ErrorRateMetricSet,
    GaugeMetric,
    InfoMetric,
)


class AUSBaseMetric(BaseModel):
    "Base class for AUS metrics"

    integration: str
    ocm_env: str


UPGRADE_SCHEDULED_METRIC_VALUE = -1.0
UPGRADE_STARTED_METRIC_VALUE = -2.0
UPGRADE_LONG_RUNNING_METRIC_VALUE = -3.0
UPGRADE_BLOCKED_METRIC_VALUE = -4.0


class AUSClusterVersionRemainingSoakDaysGauge(AUSBaseMetric, GaugeMetric):
    "Remaining days a version needs to soak for a cluster"

    cluster_uuid: str
    soaking_version: str

    @classmethod
    def name(cls) -> str:
        return "aus_cluster_version_remaining_soak_days"


class AUSClusterUpgradePolicyInfoMetric(AUSBaseMetric, InfoMetric):
    "Info metric for clusters under AUS upgrade control"

    cluster_uuid: str
    org_id: str
    org_name: str
    channel: str
    current_version: str
    cluster_name: str
    schedule: str
    sector: str
    mutexes: str
    soak_days: str
    workloads: str

    @classmethod
    def name(cls) -> str:
        return "aus_cluster_upgrade_policy_info"


class AUSOrganizationValidationErrorsGauge(AUSBaseMetric, GaugeMetric):
    "Current validation errors within an OCM organization"

    org_id: str

    @classmethod
    def name(cls) -> str:
        return "aus_organization_validation_errors"


class AUSOrganizationReconcileCounter(AUSBaseMetric, CounterMetric):
    "Counter for the number of times an OCM organization was reconciled"

    org_id: str

    @classmethod
    def name(cls) -> str:
        return "aus_organization_reconciled"


class AUSOrganizationReconcileErrorCounter(AUSBaseMetric, CounterMetric):
    "Counter for the failed reconcile runs for an OCM organization"

    org_id: str

    @classmethod
    def name(cls) -> str:
        return "aus_organization_reconcile_errors"


class AUSOrganizationErrorRate(ErrorRateMetricSet):
    "Collection of AUS metrics for an OCM organization"

    def __init__(self, integration: str, org_id: str, ocm_env: str) -> None:
        super().__init__(
            counter=AUSOrganizationReconcileCounter(
                integration=integration,
                ocm_env=ocm_env,
                org_id=org_id,
            ),
            error_counter=AUSOrganizationReconcileErrorCounter(
                integration=integration,
                ocm_env=ocm_env,
                org_id=org_id,
            ),
        )
