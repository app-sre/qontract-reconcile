from pydantic import BaseModel

from reconcile.utils.metrics import (
    CounterMetric,
    GaugeMetric,
    InfoMetric,
)


class AUSBaseMetric(BaseModel):
    "Base class for AUS metrics"

    integration: str
    ocm_env: str


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
