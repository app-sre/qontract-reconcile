from pydantic import BaseModel

from reconcile.utils.metrics import CounterMetric


class RhIdpBaseMetric(BaseModel):
    """Base class for RhIdp metrics"""

    integration: str


class RhIdpReconcileErrorCounter(RhIdpBaseMetric, CounterMetric):
    """Counter for the failed reconcile runs."""

    @classmethod
    def name(cls) -> str:
        return "RhIdp_reconcile_errors"


class RhIdpReconcileCounter(RhIdpBaseMetric, CounterMetric):
    """Counter for successful reconcile runs."""

    @classmethod
    def name(cls) -> str:
        return "rhidp_reconciled"
