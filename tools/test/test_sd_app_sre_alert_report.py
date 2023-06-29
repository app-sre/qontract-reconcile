from statistics import median

from reconcile.test.fixtures import Fixtures
from tools.sd_app_sre_alert_report import (
    gen_alert_stats,
    group_alerts,
)

messages = Fixtures("slack_api").get_anymarkup("conversations_history_messages.yaml")


def test_group_alerts():
    alerts = group_alerts(messages)

    ptf = alerts["PrometheusTargetFlapping"]
    assert ptf
    assert len(ptf) == 6

    sma = alerts["SLOMetricAbsent"]
    assert sma
    assert len(sma) == 4

    paed = alerts["PatchmanAlertEvalDelay"]
    assert paed
    assert len(paed) == 2

    csopc = alerts["ContainerSecurityOperatorPodCount"]
    assert csopc
    assert len(csopc) == 1

    # This means one of the list elements has been ignored as it didn't have alertname
    # as the total alerts we have from the above tests is 11 and the total of messages
    # from the fixture is 12.
    assert set(alerts.keys()) == {
        "PrometheusTargetFlapping",
        "SLOMetricAbsent",
        "PatchmanAlertEvalDelay",
        "ContainerSecurityOperatorPodCount",
    }
    assert len(messages) == 12


def test_alert_stats():
    alert_stats = gen_alert_stats(group_alerts(messages))

    ptf = alert_stats["PrometheusTargetFlapping"]
    assert ptf.triggered_alerts == 3
    assert ptf.resolved_alerts == 3
    assert median(ptf.elapsed_times) == 600

    sma = alert_stats["SLOMetricAbsent"]
    assert sma.triggered_alerts == 2
    assert sma.resolved_alerts == 2
    assert median(sma.elapsed_times) == 3600

    paed = alert_stats["PatchmanAlertEvalDelay"]
    assert paed.triggered_alerts == 1
    assert paed.resolved_alerts == 1
    assert not paed.elapsed_times

    csopc = alert_stats["ContainerSecurityOperatorPodCount"]
    assert csopc.triggered_alerts == 0
    assert csopc.resolved_alerts == 1
    assert not csopc.elapsed_times
