import logging

from datetime import datetime

from reconcile import queries

from reconcile.slack_base import slackapi_from_queries
from reconcile.utils.oc import OC_Map
from reconcile.utils.state import State
from reconcile.utils.defer import defer


QONTRACT_INTEGRATION = "openshift-upgrade-watcher"


@defer
def run(dry_run, thread_pool_size=10, internal=None, use_jump_host=True, defer=None):
    settings = queries.get_app_interface_settings()
    accounts = queries.get_state_aws_accounts()
    clusters = [c for c in queries.get_clusters(minimal=True) if c.get("ocm")]
    oc_map = OC_Map(
        clusters=clusters,
        integration=QONTRACT_INTEGRATION,
        settings=settings,
        internal=internal,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
    )
    defer(oc_map.cleanup)
    state = State(
        integration=QONTRACT_INTEGRATION, accounts=accounts, settings=settings
    )

    if not dry_run:
        slack = slackapi_from_queries(QONTRACT_INTEGRATION)

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
            if state.exists(state_key):
                # already notified
                continue
            logging.info(["cluster_upgrade", cluster])
            if not dry_run:
                state.add(state_key)
                usergroup = f"{cluster}-cluster"
                usergroup_id = slack.get_usergroup_id(usergroup)
                slack.chat_post_message(
                    f"Heads up <!subteam^{usergroup_id}>! "
                    + f"cluster `{cluster}` is currently "
                    + f"being upgraded to version `{version}`"
                )
