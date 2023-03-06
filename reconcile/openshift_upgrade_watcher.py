import logging
from collections.abc import (
    Callable,
    Iterable,
)
from datetime import datetime
from typing import Optional

from reconcile import queries
from reconcile.gql_definitions.common.clusters import ClusterV1
from reconcile.slack_base import slackapi_from_queries
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.clusters import get_clusters
from reconcile.utils.defer import defer
from reconcile.utils.oc_map import (
    OCLogMsg,
    OCMap,
    init_oc_map_from_clusters,
)
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.slack_api import SlackApi
from reconcile.utils.state import State

QONTRACT_INTEGRATION = "openshift-upgrade-watcher"


def cluster_slack_handle(cluster: str, slack: Optional[SlackApi]) -> str:
    usergroup = f"{cluster}-cluster"
    usergroup_id = f"@{usergroup}"
    if slack:
        usergroup_id = slack.get_usergroup_id(usergroup) or usergroup_id
    return f"<!subteam^{usergroup_id}>"


def handle_slack_notification(
    msg: str,
    slack: Optional[SlackApi],
    state: State,
    state_key: str,
    state_value: Optional[str],
) -> None:
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
    oc_map: OCMap,
    state: State,
    slack: Optional[SlackApi],
) -> None:
    now = datetime.utcnow()
    for cluster in oc_map.clusters(include_errors=True):
        oc = oc_map.get(cluster)
        if isinstance(oc, OCLogMsg):
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
            handle_slack_notification(
                msg=msg, slack=slack, state=state, state_key=state_key, state_value=None
            )


def notify_upgrades_done(
    clusters: Iterable[ClusterV1], state: State, slack: Optional[SlackApi]
) -> None:
    for cluster in clusters:
        if not cluster.spec:
            raise RuntimeError(f"Cluster '{cluster.name}' does not have any spec.")
        state_key = f"{cluster.name}-{cluster.spec.version}"
        msg = (
            f"{cluster_slack_handle(cluster.name, slack)}: "
            + f"cluster `{cluster.name}` is now running version `{cluster.spec.version}`"
        )
        handle_slack_notification(
            msg=msg,
            slack=slack,
            state=state,
            state_key=state_key,
            state_value=cluster.spec.version,
        )


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = 10,
    internal: Optional[bool] = None,
    use_jump_host: bool = True,
    defer: Optional[Callable] = None,
) -> None:
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    accounts = queries.get_state_aws_accounts()
    state = State(
        integration=QONTRACT_INTEGRATION,
        accounts=accounts,
        secret_reader=secret_reader,
    )

    clusters = [
        c for c in get_clusters() if c.ocm and not (c.spec and c.spec.hypershift)
    ]

    slack: Optional[SlackApi] = None
    if not dry_run:
        slack = slackapi_from_queries(QONTRACT_INTEGRATION)

    oc_map = init_oc_map_from_clusters(
        clusters=clusters,
        integration=QONTRACT_INTEGRATION,
        secret_reader=secret_reader,
        internal=internal,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
    )
    if defer:
        defer(oc_map.cleanup)
    notify_upgrades_start(oc_map=oc_map, state=state, slack=slack)

    notify_upgrades_done(clusters=clusters, state=state, slack=slack)
