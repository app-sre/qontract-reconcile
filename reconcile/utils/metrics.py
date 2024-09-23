import copy
import re
import threading
from abc import ABC
from collections import defaultdict
from collections.abc import (
    Generator,
    Hashable,
    Iterable,
    Sequence,
)
from types import TracebackType
from typing import (
    Any,
    TypeVar,
)

from prometheus_client.core import (
    REGISTRY,
    Counter,
    CounterMetricFamily,
    Gauge,
    GaugeMetricFamily,
    Histogram,
    Metric,
)
from prometheus_client.registry import (
    Collector,
    CollectorRegistry,
)
from pydantic import BaseModel

pushgateway_registry = CollectorRegistry()

run_time = Gauge(
    name="qontract_reconcile_last_run_seconds",
    documentation="Last run duration in seconds",
    labelnames=["integration", "shards", "shard_id"],
)

pushgateway_run_time = Gauge(
    name="qontract_reconcile_last_run_seconds",
    documentation="Last run duration in seconds",
    labelnames=["integration", "shards", "shard_id"],
    registry=pushgateway_registry,
)

run_status = Gauge(
    name="qontract_reconcile_last_run_status",
    documentation="Last run status",
    labelnames=["integration", "shards", "shard_id"],
)

pushgateway_run_status = Gauge(
    name="qontract_reconcile_last_run_status",
    documentation="Last run status",
    labelnames=["integration", "shards", "shard_id"],
    registry=pushgateway_registry,
)

execution_counter = Counter(
    name="qontract_reconcile_execution_counter",
    documentation="Counts started integration executions",
    labelnames=["integration", "shards", "shard_id"],
)

reconcile_time = Histogram(
    name="qontract_reconcile_function_" "elapsed_seconds_since_bundle_commit",
    documentation="Run time seconds for tracked " "functions",
    labelnames=["name", "integration"],
    buckets=(60.0, 150.0, 300.0, 600.0, 1200.0, 1800.0, 2400.0, 3000.0, float("inf")),
)

registry_reachouts = Counter(
    name="qontract_reconcile_registry_get_manifest_total",
    documentation="Number of GET requests on image registries",
    labelnames=["integration", "shard", "shard_id", "registry"],
)

cache_hits = Counter(
    name="qontract_reconcile_cache_hits_total",
    documentation="Number of hits to this cache",
    labelnames=["integration", "shards", "shard_id"],
)

cache_misses = Counter(
    name="qontract_reconcile_cache_misses_total",
    documentation="Number of misses on this cache",
    labelnames=["integration", "shards", "shard_id"],
)

cache_size = Gauge(
    name="qontract_reconcile_cache_cardinality",
    documentation="Number of keys in the cache",
    labelnames=["integration", "shards", "shard_id"],
)

copy_count = Counter(
    name="qontract_reconcile_skopeo_copy_total",
    documentation="Number of copy commands issued by Skopeo",
    labelnames=["integration", "shard", "shard_id"],
)

gitlab_request = Counter(
    name="qontract_reconcile_gitlab_request_total",
    documentation="Number of calls made to Gitlab API",
    labelnames=["integration"],
)

ocm_request = Counter(
    name="qontract_reconcile_ocm_request_total",
    documentation="Number of calls made to OCM API",
    labelnames=["verb", "client_id"],
)

slack_request = Counter(
    name="qontract_reconcile_slack_request_total",
    documentation="Number of calls made to Slack API",
    labelnames=["resource", "verb"],
)


#
# Class based metrics
#


class BaseMetric(ABC, BaseModel):
    @classmethod
    def name(cls) -> str:
        """
        Returns the prometheus metric name. Defaults to a snake case version of the
        class name. Removes the suffix `_metric` is present. Subclasses can override this.
        """
        metric_name = re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()
        if metric_name.endswith("_metric"):
            metric_name = metric_name[:-7]
        return metric_name


class GaugeMetric(BaseMetric):
    """
    Base class for gauge metrics.
    """

    @classmethod
    def metric_family(cls) -> GaugeMetricFamily:
        labels = [f.alias for f in cls.__fields__.values()]
        return GaugeMetricFamily(cls.name(), cls.__doc__ or "", labels=labels)

    @classmethod
    def name(cls) -> str:
        metric_name = super().name()
        if metric_name.endswith("_gauge"):
            metric_name = metric_name[:-6]
        return metric_name


class InfoMetric(GaugeMetric):
    """
    Base class for info metrics.
    """


class CounterMetric(BaseMetric):
    """
    Base class for counter metrics
    """

    @classmethod
    def metric_family(cls) -> CounterMetricFamily:
        labels = [f.alias for f in cls.__fields__.values()]
        return CounterMetricFamily(cls.name(), cls.__doc__ or "", labels=labels)

    @classmethod
    def name(cls) -> str:
        metric_name = super().name()
        if metric_name.endswith("_counter"):
            metric_name = metric_name[:-8]
        return metric_name


class MetricsContainer:
    """
    A container for metrics, supporting transactional behaviour and scoped metrics.
    """

    def __init__(
        self,
    ) -> None:
        self._gauges: dict[type[GaugeMetric], dict[Sequence[str], float]] = defaultdict(
            dict
        )
        self._counters: dict[type[CounterMetric], dict[Sequence[str], float]] = (
            defaultdict(dict)
        )

        self._scopes: dict[Hashable, MetricsContainer] = {}

    def set_gauge(self, metric: GaugeMetric, value: float) -> None:
        """
        Sets the value of the given gauge metric to the given value.
        """
        label_values = tuple(metric.dict(by_alias=True).values())
        self._gauges[metric.__class__][label_values] = value

    def set_info(self, metric: InfoMetric) -> None:
        """
        Adds an info metric. Info metrics are gauges with a value of 1,
        so they can be used to join with other metrics by multiplying.
        """
        self.set_gauge(metric, 1.0)

    def inc_counter(self, counter: CounterMetric, by: int = 1) -> None:
        """
        Increases the value of the given counter by the given amount.
        """
        # all label values need to be strings, so lets convert them
        label_values = tuple(str(v) for v in counter.dict(by_alias=True).values())
        current_value = self._counters[counter.__class__].get(label_values) or 0
        self._counters[counter.__class__][label_values] = current_value + by

    def _aggregate_scopes(self) -> "MetricsContainer":
        containers = [self]
        for sub in self._scopes.values():
            containers.append(sub._aggregate_scopes())
        return join_metric_containers(containers)

    def collect(self) -> Generator[Metric, None, None]:
        """
        Collects all metrics from this container and all its scopes.
        """
        return self._aggregate_scopes()._collect_local()

    T = TypeVar("T", bound=BaseMetric)

    def get_metric_value(self, metric_class: type[T], **kwargs: Any) -> float | None:
        """
        Finds a unique match for the metrics class and labels, and returns its value.
        If more than one match is found, a ValueError is raised.
        If no match is found, None is returned.
        """
        found = self.get_metrics(metric_class, **kwargs)
        if len(found) == 1:
            return found[0][1]
        if len(found) > 1:
            raise ValueError(
                f"More than one metric found for {metric_class} and labels {kwargs}"
            )
        return None

    def get_metrics(
        self, metric_class: type[T], **kwargs: Any
    ) -> list[tuple[T, float]]:
        """
        Returns all metrics of the given class from this container and all its scopes,
        that match (or partially match) the given labels.
        """
        mc = self._aggregate_scopes()
        metrics = {}
        if issubclass(metric_class, CounterMetric):
            metrics = mc._counters.get(metric_class, {})
        elif issubclass(metric_class, GaugeMetric):
            metrics = mc._gauges.get(metric_class, {})
        else:
            raise ValueError(f"Unknown metric class {metric_class}")

        def match_labels_predicate(metric: BaseMetric, **match_labels: Any) -> bool:
            for key, value in match_labels.items():
                if getattr(metric, key) != value:
                    return False
            return True

        unfiltered_results = [
            (
                metric_class(**{
                    key: labels[i]
                    for i, key in enumerate(metric_class.__fields__.keys())
                }),
                value,
            )
            for labels, value in metrics.items()
        ]

        return [
            (metric, value)
            for metric, value in unfiltered_results
            if match_labels_predicate(metric, **kwargs)
        ]

    def _collect_local(self) -> Generator[Metric, None, None]:
        """
        Collects only the metrics present in this container, ignoring
        any scopes.
        """
        # collect all gauges
        for gauge_metric_class, values in self._gauges.items():
            gauge_metric_family = gauge_metric_class.metric_family()
            for labels, value in values.items():
                gauge_metric_family.add_metric(
                    self._convert_labels_to_strings(labels), value
                )
            yield gauge_metric_family

        # collect all counters
        for counter_metric_class, values in self._counters.items():
            counter_metric_family = counter_metric_class.metric_family()
            for labels, value in values.items():
                counter_metric_family.add_metric(
                    self._convert_labels_to_strings(labels), value
                )
            yield counter_metric_family

    def _convert_labels_to_strings(self, raw_labels: Iterable[Any]) -> list[str]:
        return [
            str(label).lower() if isinstance(label, bool) else str(label)
            for label in raw_labels
        ]

    def clone(self, keep_gauges: bool, keep_counters: bool) -> "MetricsContainer":
        """
        Clones this container.
        """
        cloned_container = MetricsContainer()
        if keep_gauges:
            cloned_container._gauges = copy.deepcopy(self._gauges)
        if keep_counters:
            cloned_container._counters = copy.deepcopy(self._counters)
        return cloned_container

    def absorb(
        self, other: "MetricsContainer", aggregate_counters: bool = True
    ) -> None:
        """
        Absorbs the gauges and counter from the given container into this one.
        """
        # bring all gauges together
        for gauge_metric_class, values in other._gauges.items():
            self._gauges[gauge_metric_class].update(values)

        # bring all counters together, add their values up when the labels match
        for counter_metric_class, values in other._counters.items():
            if aggregate_counters:
                for labels, counter_state in values.items():
                    aggregated_counter_state = (
                        self._counters[counter_metric_class].get(labels) or 0
                    )
                    self._counters[counter_metric_class][labels] = (
                        aggregated_counter_state + counter_state
                    )
            else:
                self._counters[counter_metric_class].update(values)

        # bring scopes along
        self._scopes.update(other._scopes)


def join_metric_containers(
    metric_containers: Iterable["MetricsContainer"], aggregate_counters: bool = True
) -> "MetricsContainer":
    """
    Join all given metric containers into a single one.
    If gauge duplicates are found, the last one wins.
    If counter duplicates are found, their values are added up.
    """
    aggregated_metrics = MetricsContainer()
    for mc in metric_containers:
        aggregated_metrics.absorb(mc, aggregate_counters=aggregate_counters)
    return aggregated_metrics


class _MetricsContext:
    """
    Context manager for the metrics container. Metrics collected within the
    context will be aggregated and exposed to the prometheus client when the
    context exits.

    See `transactional_metrics` to learn more about the `scope`and `aggregate_counters`
    parameters.
    """

    def __init__(
        self,
        scope: Hashable | None,
        parent: MetricsContainer,
        aggregate_counters: bool,
    ):
        self.scope = scope
        self.parent = parent
        self.aggregate_counters = aggregate_counters

    def __enter__(self) -> MetricsContainer:
        # if the context manager is used with the scope parameter, it opens a new
        # scope within the parent container. Otherwise, it opens a new container
        # that will be absorbed into the parent container after exit
        self.container = MetricsContainer()
        if self.scope:
            previous_scope_container = self.parent._scopes.get(self.scope)
            if previous_scope_container:
                self.container = previous_scope_container.clone(
                    keep_gauges=False, keep_counters=self.aggregate_counters
                )

        _STATE.set_current_container(self.container)
        return self.container

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.scope:
            self.parent._scopes[self.scope] = self.container
        else:
            self.parent.absorb(self.container)
        _STATE.set_current_container(self.parent)


def transactional_metrics(
    scope: Hashable | None = None,
    parent_container: MetricsContainer | None = None,
    aggregate_counters: bool = True,
) -> _MetricsContext:
    """
    Creates the context manager for the metrics container, providing
    transactional behaviour. All metrics exposed within the context manager
    will be exposed only after the context manager ends.

    If a `scope` parameter is given, the metrics will be grouped by that scope
    and will replace all metrics collected in the same scope in previous runs.
    This can be used to forget metrics from previous runs and only expose the
    ones collected in the current run. For counters this is only true if
    `aggregate_counters` is set to False, which makes mostly sense if a counter
    value is provided by an external source and we want to expose the latest
    value only, so being an ever increasing gauge but with prometheus counter
    semantics. Otherwise counter metrics will be aggregated across transactions.

    If a `parent_container` is provided, the metrics will be collected in that
    container (and its scopes). If no `parent_container` is provided, the container
    of another currently running transaction will be used, if any. Otherwise the
    global container will be used.
    """
    return _MetricsContext(
        scope=scope,
        parent=(parent_container or _STATE.get_current_container()),
        aggregate_counters=aggregate_counters,
    )


class MetricCollector(Collector):
    """
    Acts as the bridge between the metrics collected in the MetricsContainers
    and the prometheus client. The `collect` function is called by the
    prometheus client during a scrape.
    """

    def __init__(self, metric_container: MetricsContainer) -> None:
        self.metric_container = metric_container
        super().__init__()

    def collect(self) -> Generator[Metric, None, None]:
        return self.metric_container.collect()


# define the top level metrics container and register it with the prometheus
_GLOBAL_METRICS_CONTAINER = MetricsContainer()
REGISTRY.register(MetricCollector(_GLOBAL_METRICS_CONTAINER))


class _CurrentContainerState(threading.local):
    """
    Thread-local state for the current metrics container.
    """

    def __init__(self) -> None:
        super().__init__()
        self.container: MetricsContainer = _GLOBAL_METRICS_CONTAINER

    def get_current_container(self) -> MetricsContainer:
        return self.container

    def set_current_container(self, container: MetricsContainer) -> None:
        self.container = container


_STATE = _CurrentContainerState()


def set_gauge(metric: GaugeMetric, value: float) -> None:
    """
    Expose a gauge metric into the current metrics container.
    Honors running transactions.
    """
    _STATE.get_current_container().set_gauge(metric, value)


def set_info(metric: InfoMetric) -> None:
    """
    Expose an info metric into the current metrics container.
    Honors running transactions.
    """
    set_gauge(metric, 1.0)


def inc_counter(counter: CounterMetric, by: int = 1) -> None:
    """
    Increases a counter in the current metrics container.
    Honors running transactions.
    """
    _STATE.get_current_container().inc_counter(counter, by)


#
# MetricSet
#


ERMS = TypeVar("ERMS", bound="ErrorRateMetricSet")


class ErrorRateMetricSet:
    """
    A context manager that exposes a counter metric and an error counter metric
    for a code block. The code block within the contextmanager is considered
    failed if an exception is raised of if the `fail` method is called.
    """

    def __init__(
        self: ERMS, counter: CounterMetric, error_counter: CounterMetric
    ) -> None:
        self._counter = counter
        self._error_counter = error_counter
        self._errors: list[BaseException] = []

    def __enter__(self: ERMS) -> ERMS:
        inc_counter(self._counter)
        return self

    def fail(self: ERMS, error: BaseException) -> None:
        """
        Mark the context as failed and record it as an event
        that increases the error counter.
        """
        self._errors.append(error)

    @property
    def failed(self: ERMS) -> bool:
        """
        Returns True if the context manager was marked as failed.
        """
        return bool(self._errors)

    @property
    def errors(self: ERMS) -> list[BaseException]:
        """
        Return the list of errors that caused the context manager to fail.
        """
        return self._errors

    def __exit__(
        self: ERMS,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_value:
            self.fail(exc_value)
        inc_counter(self._error_counter, by=(1 if self._errors else 0))


def normalize_integration_name(integration: str) -> str:
    """
    Normalize the integration name to be used in prometheus.
    """
    return integration.replace("_", "-")
