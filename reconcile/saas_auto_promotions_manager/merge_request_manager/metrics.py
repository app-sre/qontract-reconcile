from pydantic import BaseModel

from reconcile.utils.metrics import (
    CounterMetric,
    GaugeMetric,
)


class SAPMBaseMetric(BaseModel):
    "Base class for SAPM MR metrics"

    integration: str = "saas_auto_promotions_manager"


class SAPMOpenedMRsCounter(SAPMBaseMetric, CounterMetric):
    "Counter for the number of opened auto-promotion MRs"

    is_batchable: bool
    # We do not expect batches >10, i.e., cardinality will stay in check here.
    batch_size: int

    @classmethod
    def name(cls) -> str:
        return "sapm_opened_mrs"


class SAPMClosedMRsCounter(SAPMBaseMetric, CounterMetric):
    "Counter for the number of closed auto-promotion MRs"

    reason: str

    @classmethod
    def name(cls) -> str:
        return "sapm_closed_mrs"


class SAPMParallelOpenMRsGauge(SAPMBaseMetric, GaugeMetric):
    "Gauge for the number of parallel open auto-promotion MRs"

    @classmethod
    def name(cls) -> str:
        return "sapm_parallel_open_mrs"
