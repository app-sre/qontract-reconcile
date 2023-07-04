from pydantic import BaseModel

from reconcile.utils.metrics import GaugeMetric


class RhIdpBaseMetric(BaseModel):
    """Base class for RhIdp metrics"""

    integration: str
    ocm_environment: str


class RhIdpClusterCounter(RhIdpBaseMetric, GaugeMetric):
    """Number of managed clusters per organization."""

    org_id: str

    @classmethod
    def name(cls) -> str:
        return "rhidp_managed_clusters"
