from pydantic import BaseModel

from reconcile.utils.metrics import (
    CounterMetric,
    GaugeMetric,
)


class ChangeLogBaseMetric(BaseModel):
    "Base class for change-log-tracking metrics"

    integration: str = "change-log-tracking"


class ChangeLogCommitProcessed(ChangeLogBaseMetric, CounterMetric):
    "Number of commits processed by change-log-tracking"

    @classmethod
    def name(cls) -> str:
        return "change_log_commit_processed_total"


class ChangeLogAppChange(ChangeLogBaseMetric, CounterMetric):
    "Number of app-interface changes per app, labeled by product filter"

    app: str
    label_filter: str

    @classmethod
    def name(cls) -> str:
        return "change_log_app_change_total"


class ChangeLogChangeType(ChangeLogBaseMetric, CounterMetric):
    "Number of changes by change type, labeled by product filter"

    change_type: str
    label_filter: str

    @classmethod
    def name(cls) -> str:
        return "change_log_change_type_total"


class ChangeLogProcessingError(ChangeLogBaseMetric, CounterMetric):
    "Number of commit processing errors"

    @classmethod
    def name(cls) -> str:
        return "change_log_processing_error_total"


class ChangeLogItemsGauge(ChangeLogBaseMetric, GaugeMetric):
    "Total number of changelog items"

    label_filter: str

    @classmethod
    def name(cls) -> str:
        return "change_log_items"
