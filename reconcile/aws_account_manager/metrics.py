from pydantic import BaseModel

from reconcile.utils.metrics import GaugeMetric


class BaseMetric(BaseModel):
    """Base class for all AWS account manager metrics."""

    flavor: str

    @classmethod
    def name(cls) -> str:
        return "aws_account_manager"


class PayerAccountCounter(BaseMetric, GaugeMetric):
    """Number of managed payer accounts."""

    @classmethod
    def name(cls) -> str:
        return super().name() + "_payer_account_count"


class OrgAccountCounter(BaseMetric, GaugeMetric):
    """Number of managed organization accounts per payer account."""

    payer_account: str

    @classmethod
    def name(cls) -> str:
        return super().name() + "_org_account_count"


class NonOrgAccountCounter(BaseMetric, GaugeMetric):
    """Number of managed non-organization accounts."""

    @classmethod
    def name(cls) -> str:
        return super().name() + "_non_org_account_count"
