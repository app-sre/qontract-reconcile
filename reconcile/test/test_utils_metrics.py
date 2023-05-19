import pytest
from prometheus_client.core import (
    CounterMetricFamily,
    GaugeMetricFamily,
)

from reconcile.utils.metrics import (
    CounterMetric,
    GaugeMetric,
    InfoMetric,
    MetricsContainer,
    inc_counter,
    join_metric_containers,
    set_gauge,
    transactional_metrics,
)


class DemoGauge(GaugeMetric):
    "demo gauge metric"

    field: str

    @classmethod
    def name(cls) -> str:
        return "demo_gauge"


class DemoCounter(CounterMetric):
    "demo counter metric"

    field: str

    @classmethod
    def name(cls) -> str:
        return "demo_counter"


class DemoInfoMetric(InfoMetric):
    "demo info metric"

    string_field: str
    int_field: int
    bool_field: bool

    @classmethod
    def name(cls) -> str:
        return "some_demo_info_metric"


@pytest.fixture
def demo_counter() -> DemoCounter:
    return DemoCounter(field="field_value")


@pytest.fixture
def demo_gauge() -> DemoGauge:
    return DemoGauge(field="field_value")


#
# metric families
#


def test_gauge_metric_family() -> None:
    metric_family = DemoGauge.metric_family()
    assert isinstance(metric_family, GaugeMetricFamily)
    assert metric_family.name == "demo_gauge"
    assert metric_family.documentation == "demo gauge metric"
    assert set(metric_family._labelnames) == {"field"}


def test_counter_metric_family() -> None:
    metric_family = DemoCounter.metric_family()
    assert isinstance(metric_family, CounterMetricFamily)
    assert metric_family.name == "demo_counter"
    assert metric_family.documentation == "demo counter metric"
    assert set(metric_family._labelnames) == {"field"}


def test_info_metric_family() -> None:
    metric_family = DemoInfoMetric.metric_family()
    assert isinstance(metric_family, GaugeMetricFamily)
    assert metric_family.name == "some_demo_info_metric"
    assert metric_family.documentation == "demo info metric"
    assert set(metric_family._labelnames) == {"string_field", "int_field", "bool_field"}


#
# metric names
#


def test_default_counter_metric_name() -> None:
    class AppErrors(CounterMetric):
        field: str

    assert AppErrors.name() == "app_errors"


def test_default_counter_metric_name_remove_metric_suffix() -> None:
    class AppErrorsMetric(CounterMetric):
        field: str

    assert AppErrorsMetric.name() == "app_errors"


def test_default_counter_metric_name_remove_counter_suffix() -> None:
    class AppErrorsCounter(CounterMetric):
        field: str

    assert AppErrorsCounter.name() == "app_errors"


def test_default_gauge_metric_name_remove_metric_suffix() -> None:
    class AppRuntimeMetric(GaugeMetric):
        field: str

    assert AppRuntimeMetric.name() == "app_runtime"


def test_default_gauge_metric_name_remove_gauge_suffix() -> None:
    class AppRuntimeGauge(GaugeMetric):
        field: str

    assert AppRuntimeGauge.name() == "app_runtime"


def test_default_info_metric_name_remove_metric_suffix() -> None:
    class AppInfoMetric(InfoMetric):
        field: str

    assert AppInfoMetric.name() == "app_info"


#
# metric label type conversion
#


def test_metric_non_string_label_conversion() -> None:
    info_metric = DemoInfoMetric(string_field="string", int_field=42, bool_field=True)
    container = MetricsContainer()
    container.set_info(info_metric)

    metrics = list(container.collect())
    sample = metrics[0].samples[0]
    assert sample.labels == {
        "string_field": "string",
        "int_field": "42",
        "bool_field": "true",
    }
    assert sample.value == 1


#
# metrics container counter
#


def test_metrics_container_inc_counter(demo_counter: DemoCounter) -> None:
    container = MetricsContainer()
    container.inc_counter(demo_counter)
    container.inc_counter(demo_counter, by=2)

    metrics = list(container.collect())
    assert metrics[0].type == "counter"
    assert len(metrics[0].samples) == 1
    sample = metrics[0].samples[0]
    assert sample.labels == demo_counter.dict(by_alias=True)
    assert sample.value == 3


#
# metric container aborb
#


@pytest.mark.parametrize(
    "aggregate_counters,expected_counter_value",
    [
        (True, 3),
        (False, 2),
    ],
)
def test_metric_container_absorb_counters(
    demo_counter: DemoCounter, aggregate_counters: bool, expected_counter_value: int
) -> None:
    container = MetricsContainer()
    container.inc_counter(demo_counter)

    another_container = MetricsContainer()
    another_container.inc_counter(demo_counter, by=2)

    container.absorb(another_container, aggregate_counters=aggregate_counters)

    metrics = list(container.collect())
    assert metrics[0].type == "counter"
    assert len(metrics[0].samples) == 1
    assert metrics[0].samples[0].value == expected_counter_value


def test_metric_container_absorb_gauges(demo_gauge: DemoGauge) -> None:
    container = MetricsContainer()
    container.set_gauge(demo_gauge, 10)

    another_container = MetricsContainer()
    another_container.set_gauge(demo_gauge, 20)

    container.absorb(another_container)

    metrics = list(container.collect())
    assert metrics[0].type == "gauge"
    assert len(metrics[0].samples) == 1
    assert metrics[0].samples[0].value == 20


def test_metric_container_absorb_with_scopes(
    demo_gauge: DemoGauge, demo_counter: DemoCounter
) -> None:
    container = MetricsContainer()
    container.set_gauge(demo_gauge, 10)

    another_container = MetricsContainer()
    with transactional_metrics("some-scope", another_container):
        inc_counter(demo_counter)

    container.absorb(another_container)
    metrics = list(container.collect())
    assert len(metrics) == 2


#
# metrics container join
#


def test_metrics_container_join_counters() -> None:
    cnt_1 = DemoCounter(field="1")
    cnt_2 = DemoCounter(field="2")
    cnt_shared = DemoCounter(field="shared")

    container_1 = MetricsContainer()
    container_1.inc_counter(cnt_1)
    container_1.inc_counter(cnt_shared)

    container_2 = MetricsContainer()
    container_2.inc_counter(cnt_2)
    container_2.inc_counter(cnt_shared, by=2)

    joined_container = join_metric_containers([container_1, container_2])

    metrics = list(joined_container.collect())
    assert metrics[0].type == "counter"
    assert len(metrics[0].samples) == 3

    for s in metrics[0].samples:
        if s.labels["field"] == "1":
            assert s.value == 1
        elif s.labels["field"] == "2":
            assert s.value == 1
        elif s.labels["field"] == "shared":
            assert s.value == 3


def test_metrics_container_join_gauges() -> None:
    g_1 = DemoGauge(field="1")
    g_2 = DemoGauge(field="2")
    g_shared = DemoGauge(field="shared")

    container_1 = MetricsContainer()
    container_1.set_gauge(g_1, 1)
    container_1.set_gauge(g_shared, 1)

    container_2 = MetricsContainer()
    container_2.set_gauge(g_2, 2)
    container_2.set_gauge(g_shared, 2)

    joined_container = join_metric_containers([container_1, container_2])

    metrics = list(joined_container.collect())
    assert metrics[0].type == "gauge"
    assert len(metrics[0].samples) == 3

    for s in metrics[0].samples:
        if s.labels["field"] == "1":
            assert s.value == 1
        elif s.labels["field"] == "2":
            assert s.value == 2
        elif s.labels["field"] == "shared":
            assert s.value == 2


#
# transactional metrics
#


def test_transactional_metrics(
    demo_gauge: DemoGauge, demo_counter: DemoCounter
) -> None:
    root = MetricsContainer()
    with transactional_metrics("scope", root) as c:
        c.set_gauge(demo_gauge, 42)
        c.inc_counter(demo_counter)

        # the transaction is still pending so we should not see the metrics in root
        assert len(list(root.collect())) == 0

    # the transaction is committed so we should see the metrics in root
    assert len(list(root.collect())) == 2


def test_transactional_metrics_gauge_same_scope() -> None:
    """
    A transaction with the same scope as an earlier transaction should override
    the earlier transactions gauges.
    """
    g_1 = DemoGauge(field="1", another_field_alias="1")
    g_2 = DemoGauge(field="2", another_field_alias="2")

    scope = "scope"
    root = MetricsContainer()
    with transactional_metrics(scope, root) as c:
        c.set_gauge(g_1, 42)
        # the transaction is still pending so we should not see the gauge in root
        assert len(list(root.collect())) == 0

    # now that the transaction is committed we should see the gauge value in root
    metrics = list(root.collect())
    samples = metrics[0].samples
    assert len(samples) == 1
    assert samples[0].labels == g_1.dict(by_alias=True)
    assert samples[0].value == 42

    with transactional_metrics(scope, root) as c:
        c.set_gauge(g_2, 84)
        # the transaction is still pending so we should still see the gauge from the previous transaction
        # and the new gauge should not be visible
        metrics = list(root.collect())
        assert len(metrics) == 1
        samples = metrics[0].samples
        assert len(samples) == 1
        assert samples[0].labels == g_1.dict(by_alias=True)
        assert samples[0].value == 42

    # now that the transaction is committed we should see the new gauge value in root
    metrics = list(root.collect())
    samples = metrics[0].samples
    assert len(samples) == 1
    assert samples[0].labels == g_2.dict(by_alias=True)
    assert samples[0].value == 84


def test_transactional_metrics_gauges_different_scope() -> None:
    """
    Two transactions with different scopes should not replace each others gauges.
    """
    g_1 = DemoGauge(field="1", another_field_alias="1")
    g_2 = DemoGauge(field="2", another_field_alias="2")

    root = MetricsContainer()
    with transactional_metrics("scope-1", root) as c:
        c.set_gauge(g_1, 42)

    with transactional_metrics("scope-2", root) as c:
        c.set_gauge(g_2, 84)

    # now that the transaction is committed we should see the new metric value in root
    metrics = list(root.collect())
    samples = metrics[0].samples
    assert len(samples) == 2
    for s in samples:
        if s.labels["field"] == "1":
            assert s.value == 42
        elif s.labels["field"] == "2":
            assert s.value == 84


def test_transactional_metrics_counter_same_scope() -> None:
    """
    Counter values are kept between transactions with the same scope.
    Transactional visibility still applies.
    """
    cnt = DemoCounter(field="1", another_field_alias="1")

    scope = "scope"
    root = MetricsContainer()
    with transactional_metrics(scope, root) as c:
        c.inc_counter(cnt)
        # the transaction is still pending so we should not see the counter in root
        assert len(list(root.collect())) == 0

    metrics = list(root.collect())
    samples = metrics[0].samples
    assert len(samples) == 1
    assert samples[0].labels == cnt.dict(by_alias=True)
    assert samples[0].value == 1

    with transactional_metrics(scope, root) as c:
        # we took the previous counter with us, so we should see it within this pending transaction
        assert len(list(c.collect())) == 1

        c.inc_counter(cnt)

        # the transaction is still pending so while we should see the counter increased within the transaction
        assert list(c.collect())[0].samples[0].value == 2

        # ... we should not see the counter increased in root yet
        assert list(root.collect())[0].samples[0].value == 1

    # but when the transaction is committed we should see the counter increased in root
    assert list(root.collect())[0].samples[0].value == 2


def test_transactional_metrics_counter_different_scope() -> None:
    """
    Counter values are aggregated between transactions with different scopes.
    """
    cnt = DemoCounter(field="1", another_field_alias="1")

    root = MetricsContainer()
    with transactional_metrics("scope-1", root) as c:
        c.inc_counter(cnt)

    metrics = list(root.collect())
    samples = metrics[0].samples
    assert len(samples) == 1
    assert samples[0].labels == cnt.dict(by_alias=True)
    assert samples[0].value == 1

    with transactional_metrics("scope-2", root) as c:
        # we are in a different scope so we don't see the counter from the previous transaction
        assert len(list(c.collect())) == 0

        c.inc_counter(cnt)

        # now we see the counter but it has value 1, so freshly initialized
        assert list(c.collect())[0].samples[0].value == 1

    # but when the transaction is committed we should see the counter values from both scopes aggregated in root
    assert list(root.collect())[0].samples[0].value == 2


#
# implicit nested transaction
#


def test_transactional_metrics_implicitely_nested(demo_gauge: DemoGauge) -> None:
    """
    Nested transactions should be implicitely nested without the need to pass the parent container.
    """
    root = MetricsContainer()
    with transactional_metrics(parent_container=root) as outer:
        set_gauge(demo_gauge, 42)

        # the transaction is still pending so we should not see the metric in root
        assert len(list(root.collect())) == 0

        # nested transaction called without explicit parent so it
        # should automatically be nested within the outer transaction
        with transactional_metrics():
            set_gauge(demo_gauge, 84)

            # the transaction is still pending so we should not see the metrics in root
            assert len(list(root.collect())) == 0

            # the value in the outer transaction should not be affected
            assert list(outer.collect())[0].samples[0].value == 42

    # the transaction is committed so we should see the metrics in root
    assert len(list(root.collect())) == 1
    assert list(root.collect())[0].samples[0].value == 84
