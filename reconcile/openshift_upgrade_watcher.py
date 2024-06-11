import logging
from collections.abc import (
    Callable,
    Iterable,
)
from datetime import datetime

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
from reconcile.utils.ocm import OCMMap
from reconcile.utils.ocm.upgrades import get_control_plane_upgrade_policies
from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.slack_api import SlackApi
from reconcile.utils.state import (
    State,
    init_state,
)

QONTRACT_INTEGRATION = "openshift-upgrade-watcher"


def cluster_slack_handle(cluster: str, slack: SlackApi | None) -> str:
    usergroup = f"{cluster}-cluster"
    usergroup_id = f"@{usergroup}"
    if slack:
        usergroup_id = slack.get_usergroup_id(usergroup) or usergroup_id
    return f"<!subteam^{usergroup_id}>"


def handle_slack_notification(
    msg: str,
    slack: SlackApi | None,
    state: State,
    state_key: str,
    state_value: str | None,
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


def _get_start_osd(oc_map: OCMap, cluster_name: str) -> tuple[str | None, str | None]:
    oc = oc_map.get(cluster_name)
    if isinstance(oc, OCLogMsg):
        logging.log(level=oc.log_level, msg=oc.message)
        return None, None

    upgrade_config = oc.get(
        namespace="openshift-managed-upgrade-operator",
        kind="UpgradeConfig",
        allow_not_found=True,
    )["items"]
    if not upgrade_config:
        logging.debug(f"[{cluster_name}] UpgradeConfig not found.")
        return None, None
    [upgrade_config] = upgrade_config

    upgrade_spec = upgrade_config["spec"]
    upgrade_at = upgrade_spec["upgradeAt"]
    version = upgrade_spec["desired"]["version"]
    return upgrade_at, version


def _get_start_hypershift(
    ocm_api: OCMBaseClient, cluster_id: str
) -> tuple[str | None, str | None]:
    schedules = get_control_plane_upgrade_policies(ocm_api, cluster_id)
    schedule = [s for s in schedules if s["state"] == "started"]
    if not schedule:
        return None, None

    if len(schedule) > 1:
        logging.error(f"[{cluster_id}] More than one schedule started.")

    return schedule[0]["next_run"], schedule[0]["version"]


def notify_upgrades_start(
    clusters: list[ClusterV1],
    oc_map: OCMap,
    ocm_map: OCMMap,
    state: State,
    slack: SlackApi | None,
) -> None:
    now = datetime.utcnow()
    for cluster in clusters:
        if cluster.spec and not cluster.spec.hypershift:
            upgrade_at, version = _get_start_osd(oc_map, cluster.name)
        elif cluster.spec and cluster.spec.q_id:
            upgrade_at, version = _get_start_hypershift(
                ocm_map.get(cluster.name)._ocm_client, cluster.spec.q_id
            )
        else:
            continue

        if upgrade_at and version:
            upgrade_at_obj = datetime.strptime(upgrade_at, "%Y-%m-%dT%H:%M:%SZ")
            state_key = f"{cluster.name}-{upgrade_at}1"
            # if this is the first iteration in which 'now' had passed
            # the upgrade at date time, we send a notification
            if upgrade_at_obj < now:
                msg = (
                    f"Heads up {cluster_slack_handle(cluster.name, slack)}! "
                    + f"cluster `{cluster.name}` is currently "
                    + f"being upgraded to version `{version}`"
                )
                handle_slack_notification(
                    msg=msg,
                    slack=slack,
                    state=state,
                    state_key=state_key,
                    state_value=None,
                )


def notify_cluster_new_version(
    clusters: Iterable[ClusterV1], state: State, slack: SlackApi | None
) -> None:
    # Send a notification, if a cluster runs a version it was not running in the past
    # This does not check if an upgrade was successful or not
    for cluster in clusters:
        if cluster.spec:
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
    internal: bool | None = None,
    use_jump_host: bool = True,
    defer: Callable | None = None,
) -> None:
    slack: SlackApi | None = None
    if not dry_run:
        slack = slackapi_from_queries(QONTRACT_INTEGRATION)

    vault_settings = get_app_interface_vault_settings()
    settings = queries.get_app_interface_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    state = init_state(integration=QONTRACT_INTEGRATION, secret_reader=secret_reader)
    if defer:
        defer(state.cleanup)

    clusters = [c for c in get_clusters() if c.ocm and c.spec]

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

    cluster_like_objects = [cluster.dict(by_alias=True) for cluster in clusters]
    ocm_map = OCMMap(
        clusters=cluster_like_objects,
        integration=QONTRACT_INTEGRATION,
        settings=settings,
    )

    notify_upgrades_start(
        clusters=clusters, oc_map=oc_map, ocm_map=ocm_map, state=state, slack=slack
    )

    notify_cluster_new_version(clusters=clusters, state=state, slack=slack)
