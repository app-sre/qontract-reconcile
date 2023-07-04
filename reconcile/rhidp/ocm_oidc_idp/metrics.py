from reconcile.rhidp.metrics import RhIdpBaseMetric
from reconcile.utils.metrics import CounterMetric


class RhIdpOCMOidcIdpReconcileErrorCounter(RhIdpBaseMetric, CounterMetric):
    """Counter for the failed reconcile runs."""

    ocm_environment: str

    @classmethod
    def name(cls) -> str:
        return "rhidp_ocm_oidc_idp_reconcile_errors"


class RhIdpOCMOidcIdpReconcileCounter(RhIdpBaseMetric, CounterMetric):
    """Counter for successful reconcile runs."""

    ocm_environment: str

    @classmethod
    def name(cls) -> str:
        return "rhidp_ocm_oidc_idp_reconciled"
