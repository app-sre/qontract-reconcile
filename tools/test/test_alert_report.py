from statistics import median

from reconcile.test.fixtures import Fixtures
from tools.alert_report import (
    gen_alert_stats,
    group_alerts,
)

# Messages with cluster-name prefix in the attachment title, e.g.
# "[appsrep11ue1]Alert: AlertName [FIRING:1]  message"
# introduced when the Alertmanager Slack template was updated to include the cluster.
CLUSTER_PREFIXED_MESSAGES = [
    {
        "subtype": "bot_message",
        "bot_id": "BFYPB540Z",
        "ts": "1750000200.000000",
        "username": "app-sre-alerts (appsrep11ue1)",
        "attachments": [
            {
                "title": "[appsrep11ue1]Alert: ClusterPrefixedAlert [RESOLVED]  some alert message"
            }
        ],
    },
    {
        "subtype": "bot_message",
        "bot_id": "BFYPB540Z",
        "ts": "1750000100.000000",
        "username": "app-sre-alerts (appsrep11ue1)",
        "attachments": [
            {
                "title": "[appsrep11ue1]Alert: ClusterPrefixedAlert [FIRING:1]  some alert message"
            }
        ],
    },
]

# Bot OAuth app messages (used since the incoming-webhook was rotated on
# 2026-05-14) have no "username" field at all, only "bot_id" — which is the
# same for every cluster. Cluster identity now only comes from the title
# prefix, so two different clusters firing the same alert/message must stay
# separate.
BOT_ONLY_MULTI_CLUSTER_MESSAGES = [
    {
        "subtype": "bot_message",
        "bot_id": "B0B3Y3X62AW",
        "ts": "1750000400.000000",
        "attachments": [
            {"title": "[clusterB]Alert: SharedAlert [RESOLVED]  same message"}
        ],
    },
    {
        "subtype": "bot_message",
        "bot_id": "B0B3Y3X62AW",
        "ts": "1750000300.000000",
        "attachments": [
            {"title": "[clusterB]Alert: SharedAlert [FIRING:1]  same message"}
        ],
    },
    {
        "subtype": "bot_message",
        "bot_id": "B0B3Y3X62AW",
        "ts": "1750000100.000000",
        "attachments": [
            {"title": "[clusterA]Alert: SharedAlert [FIRING:1]  same message"}
        ],
    },
]

# Bot message without a cluster-prefixed title (defensive edge case): falls
# back to bot_id rather than raising KeyError.
BOT_ONLY_NO_CLUSTER_PREFIX_MESSAGES = [
    {
        "subtype": "bot_message",
        "bot_id": "B0B3Y3X62AW",
        "ts": "1750000500.000000",
        "attachments": [{"title": "Alert: NoUsernameAlert [FIRING:1]  message text"}],
    },
]

messages = Fixtures("slack_api").get_anymarkup("conversations_history_messages.yaml")


def test_group_alerts() -> None:
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

    art = alerts["AlertmanagerReceiverTest"]
    assert art
    assert len(art) == 2

    # This means one of the list elements has been ignored as it didn't have alertname
    # as the total alerts we have from the above tests is 13 and the total of messages
    # from the fixture is 14.
    assert set(alerts.keys()) == {
        "PrometheusTargetFlapping",
        "SLOMetricAbsent",
        "PatchmanAlertEvalDelay",
        "ContainerSecurityOperatorPodCount",
        "AlertmanagerReceiverTest",
    }
    assert len(messages) == 14


def test_alert_stats() -> None:
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

    art = alert_stats["AlertmanagerReceiverTest"]
    assert art.triggered_alerts == 1
    assert art.resolved_alerts == 1
    assert median(art.elapsed_times) == 300


def test_group_alerts_cluster_prefixed_title() -> None:
    """Attachment titles with a [cluster] prefix are parsed correctly."""
    alerts = group_alerts(CLUSTER_PREFIXED_MESSAGES)
    assert "ClusterPrefixedAlert" in alerts
    assert len(alerts["ClusterPrefixedAlert"]) == 2


def test_alert_stats_cluster_prefixed_title() -> None:
    alert_stats = gen_alert_stats(group_alerts(CLUSTER_PREFIXED_MESSAGES))
    stat = alert_stats["ClusterPrefixedAlert"]
    assert stat.triggered_alerts == 1
    assert stat.resolved_alerts == 1
    assert len(stat.elapsed_times) == 1


def test_group_alerts_bot_message_without_username() -> None:
    """Bot OAuth app messages have no 'username' field and must not raise KeyError."""
    alerts = group_alerts(BOT_ONLY_MULTI_CLUSTER_MESSAGES)
    assert "SharedAlert" in alerts
    assert len(alerts["SharedAlert"]) == 3
    # The shared bot_id must not be used as the grouping key when a cluster
    # name is available from the title prefix.
    assert {a.username for a in alerts["SharedAlert"]} == {"clusterA", "clusterB"}


def test_alert_stats_bot_message_without_username_keeps_clusters_separate() -> None:
    stat = gen_alert_stats(group_alerts(BOT_ONLY_MULTI_CLUSTER_MESSAGES))["SharedAlert"]
    # Both clusters fired, but only clusterB resolved.
    assert stat.triggered_alerts == 2
    assert stat.resolved_alerts == 1
    assert stat.elapsed_times == [100.0]


def test_group_alerts_bot_message_falls_back_to_bot_id() -> None:
    """Without a cluster-prefixed title either, fall back to bot_id."""
    alerts = group_alerts(BOT_ONLY_NO_CLUSTER_PREFIX_MESSAGES)
    assert alerts["NoUsernameAlert"][0].username == "B0B3Y3X62AW"
