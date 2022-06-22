import logging

from datetime import datetime
from typing import Optional

from reconcile import queries

from reconcile.slack_base import slackapi_from_queries
from reconcile.utils.oc import OC_Map
from reconcile.utils.slack_api import SlackApi
from reconcile.utils.state import State
from reconcile.utils.defer import defer


QONTRACT_INTEGRATION = "openshift-upgrade-watcher"


def cluster_slack_handle(cluster: str, slack: Optional[SlackApi]):
    usergroup = f"{cluster}-cluster"
    usergroup_id = f"@{usergroup}"
    if slack:
        usergroup_id = slack.get_usergroup_id(usergroup)
    return f"<!subteam^{usergroup_id}>"


def handle_slack_notification(
    msg: str,
    slack: Optional[SlackApi],
    state: State,
    state_key: str,
    state_value: Optional[str],
):
    """Check notification status, notify if needed and update the notification status"""
    if state.exists(state_key) and state.get(state_key) == state_value:
        # already notified for this state key & value
        return
    logging.info(["openshift-upgrade-watcher", msg])
    if not slack:
        return
    slack.chat_post_message(msg)
    state.add(state_key, state_value, force=True)


def notify_upgrades_start(
    oc_map: OC_Map,
    state: State,
    slack: Optional[SlackApi],
):
    now = datetime.utcnow()
    for cluster in oc_map.clusters(include_errors=True):
        oc = oc_map.get(cluster)
        if not oc:
            logging.log(level=oc.log_level, msg=oc.message)
            continue
        upgrade_config = oc.get(
            namespace="openshift-managed-upgrade-operator",
            kind="UpgradeConfig",
            allow_not_found=True,
        )["items"]
        if not upgrade_config:
            logging.debug(f"[{cluster}] UpgradeConfig not found.")
            continue
        [upgrade_config] = upgrade_config

        upgrade_spec = upgrade_config["spec"]
        upgrade_at = upgrade_spec["upgradeAt"]
        version = upgrade_spec["desired"]["version"]
        upgrade_at_obj = datetime.strptime(upgrade_at, "%Y-%m-%dT%H:%M:%SZ")
        state_key = f"{cluster}-{upgrade_at}"
        # if this is the first iteration in which 'now' had passed
        # the upgrade at date time, we send a notification
        if upgrade_at_obj < now:
            msg = (
                f"Heads up {cluster_slack_handle(cluster, slack)}! "
                + f"cluster `{cluster}` is currently "
                + f"being upgraded to version `{version}`"
            )
            handle_slack_notification(msg, slack, state, state_key, None)


def notify_upgrades_done(clusters: list[dict], state: State, slack: Optional[SlackApi]):
    for cluster in clusters:
        cluster_name = cluster["name"]
        version = cluster["spec"]["version"]
        state_key = f"{cluster_name}-{version}"
        msg = (
            f"{cluster_slack_handle(cluster_name, slack)}: "
            + f"cluster `{cluster_name}` is now running version `{version}`"
        )
        handle_slack_notification(msg, slack, state, state_key, version)


@defer
def run(dry_run, thread_pool_size=10, internal=None, use_jump_host=True, defer=None):
    settings = queries.get_app_interface_settings()
    accounts = queries.get_state_aws_accounts()
    state = State(
        integration=QONTRACT_INTEGRATION, accounts=accounts, settings=settings
    )

    clusters = [c for c in queries.get_clusters() if c.get("ocm")]

    slack: Optional[SlackApi] = None
    if not dry_run:
        slack = slackapi_from_queries(QONTRACT_INTEGRATION)

    oc_map = OC_Map(
        clusters=clusters,
        integration=QONTRACT_INTEGRATION,
        settings=settings,
        internal=internal,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
    )
    defer(oc_map.cleanup)
    notify_upgrades_start(oc_map, state, slack)

    notify_upgrades_done(clusters, state, slack)
