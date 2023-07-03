from reconcile.rhidp.metrics import RhIdpBaseMetric
from reconcile.utils.metrics import (
    CounterMetric,
    GaugeMetric,
)


class RhIdpSSOClientReconcileErrorCounter(RhIdpBaseMetric, CounterMetric):
    """Counter for the failed reconcile runs."""

    @classmethod
    def name(cls) -> str:
        return "rhidp_sso_client_reconcile_errors"


class RhIdpSSOClientReconcileCounter(RhIdpBaseMetric, CounterMetric):
    """Counter for successful reconcile runs."""

    @classmethod
    def name(cls) -> str:
        return "rhidp_sso_client_reconciled"


class RhIdpSSOClientIatExpiration(RhIdpBaseMetric, GaugeMetric):
    """Gauge for the expiration of the initial access token."""

    path: str

    @classmethod
    def name(cls) -> str:
        return "rhidp_sso_client_inital_access_token_expiration"


class RhIdpSSOClientCounter(RhIdpBaseMetric, GaugeMetric):
    """Number of existing SSO clients."""

    @classmethod
    def name(cls) -> str:
        return "rhidp_sso_client_number_of_clients"
