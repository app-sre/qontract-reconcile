from enum import StrEnum

from pydantic import BaseModel

from reconcile.utils.metrics import (
    CounterMetric,
    GaugeMetric,
)


class OCMUserManagementBaseMetric(BaseModel):
    "Base class for OCM user management metrics"

    integration: str
    ocm_env: str


class OCMUserManagementOrganizationValidationErrorsGauge(
    OCMUserManagementBaseMetric, GaugeMetric
):
    "Current validation errors within an OCM organization"

    org_id: str

    @classmethod
    def name(cls) -> str:
        return "oum_organization_validation_errors"


class OCMUserManagementOrganizationReconcileCounter(
    OCMUserManagementBaseMetric, CounterMetric
):
    "Counter for the number of times an OCM organization was reconciled"

    org_id: str

    @classmethod
    def name(cls) -> str:
        return "oum_organization_reconciled"


class OCMUserManagementOrganizationReconcileErrorCounter(
    OCMUserManagementBaseMetric, CounterMetric
):
    "Counter for the failed reconcile runs for an OCM organization"

    org_id: str

    @classmethod
    def name(cls) -> str:
        return "oum_organization_reconcile_errors"


class OCMUserManagementOrganizationActionCounter(
    OCMUserManagementBaseMetric, CounterMetric
):
    "Counter for the number of actions taken for an OCM organization"

    class Action(StrEnum):
        AddUser = "add-user"
        RemoveUser = "remove-user"

        def __str__(self) -> str:
            return self.value

    org_id: str
    action: Action

    @classmethod
    def name(cls) -> str:
        return "oum_organization_actions"
