from typing import Any

from reconcile import (
    openshift_users,
    queries,
    slack_usergroups,
)
from reconcile.slack_base import slackapi_from_queries
from reconcile.slack_usergroups import (
    SlackMap,
    SlackObject,
    State,
    WorkspaceSpec,
)
from reconcile.utils.slack_api import (
    SlackApi,
    UsergroupNotFoundException,
)

QONTRACT_INTEGRATION = "slack-cluster-usergroups"


def get_slack_username(user: dict[str, Any]) -> str:
    return user["slack_username"] or user["org_username"]


def include_user(user, cluster_name, cluster_users):
    # if user does not have access to the cluster
    if user["github_username"] not in cluster_users:
        return False
    # do nothing when tag_on_cluster_updates is not defined
    tag_on_cluster_updates = user.get("tag_on_cluster_updates")
    if tag_on_cluster_updates is True:
        return True
    elif tag_on_cluster_updates is False:
        return False

    # if a user has access via a role
    # check if that role grants access to the current cluster
    # if all roles that grant access to the current cluster also
    # have 'tag_on_cluster_updates: false' - remove the user
    role_result = None
    for role in user["roles"]:
        access = role.get("access")
        if not access:
            continue
        for a in access:
            cluster = a.get("cluster")
            if cluster:
                if cluster["name"] == cluster_name:
                    if role.get("tag_on_cluster_updates") is False:
                        role_result = role_result or False
                    else:
                        role_result = True
                continue
            namespace = a.get("namespace")
            if namespace:
                if namespace["cluster"]["name"] == cluster_name:
                    if role.get("tag_on_cluster_updates") is False:
                        role_result = role_result or False
                    else:
                        role_result = True

    result = False if role_result is False else True
    return result


def get_desired_state(slack: SlackApi) -> dict[str, Any]:
    """
    Get the desired state of the Slack cluster usergroups.

    :param slack: client for calling Slack API
    :type slack: reconcile.utils.slack_api.SlackApi

    :return: desired state data, keys are workspace -> usergroup
                (ex. state['coreos']['app-sre-ic']
    :rtype: dict
    """
    desired_state: dict[str, Any] = {}
    all_users = queries.get_roles(
        sendgrid=False, saas_files=False, aws=False, permissions=False
    )
    all_clusters = queries.get_clusters(minimal=True)
    # this needs to be refactored - https://issues.redhat.com/browse/APPSRE-6575
    clusters = [
        c
        for c in all_clusters
        for auth in c["auth"]
        if auth.get("team") and c.get("ocm")
    ]
    openshift_users_desired_state = openshift_users.fetch_desired_state(oc_map=None)
    for cluster in clusters:
        cluster_name = cluster["name"]
        cluster_users = [
            u["user"]
            for u in openshift_users_desired_state
            if u["cluster"] == cluster_name
        ]
        usergroup = None
        for auth in cluster["auth"]:
            if not auth.get("team"):
                continue
            usergroup = auth["team"]
        if not usergroup:
            # this is an edge case and should not happen and will be addressed later
            # https://issues.redhat.com/browse/APPSRE-6575
            continue

        ugid = slack.get_usergroup_id(usergroup)
        user_names = [
            get_slack_username(u)
            for u in all_users
            if include_user(u, cluster_name, cluster_users)
        ]
        slack_users = {
            SlackObject(pk=pk, name=name)
            for pk, name in slack.get_users_by_names(user_names).items()
        }
        slack_channels = {
            SlackObject(pk=pk, name=name)
            for pk, name in slack.get_channels_by_names([slack.channel]).items()  # type: ignore[list-item] # will be address later in APPSRE-6593
        }
        desired_state.setdefault(slack.workspace_name, {})[usergroup] = State(
            workspace=slack.workspace_name,
            usergroup=usergroup,
            usergroup_id=ugid,
            users=slack_users,
            channels=slack_channels,
            description=f"Users with access to the {cluster_name} cluster",
        )

    return desired_state


def get_current_state(slack: SlackApi, usergroups: list[str]) -> dict[str, Any]:
    """
    Get the current state of the Slack cluster usergroups.

    :param slack: client for calling Slack API
    :type slack: reconcile.utils.slack_api.SlackApi

    :param usergroups: cluster usergroups to get state of
    :type usergroups: Iterable

    :return: current state data, keys are workspace -> usergroup
                (ex. state['coreos']['app-sre-ic']
    :rtype: dict
    """
    current_state: dict[str, Any] = {}

    for ug in usergroups:
        try:
            users, channels, description = slack.describe_usergroup(ug)
        except UsergroupNotFoundException:
            continue
        current_state.setdefault(slack.workspace_name, {})[ug] = State(
            workspace=slack.workspace_name,
            usergroup=ug,
            users={SlackObject(pk=pk, name=name) for pk, name in users.items()},
            channels={SlackObject(pk=pk, name=name) for pk, name in channels.items()},
            description=description,
        )

    return current_state


def run(dry_run: bool) -> None:
    slack = slackapi_from_queries(QONTRACT_INTEGRATION)
    desired_state = get_desired_state(slack)
    usergroups = []
    for _, workspace_state in desired_state.items():
        for usergroup, _ in workspace_state.items():
            usergroups.append(usergroup)
    current_state = get_current_state(slack, usergroups)

    # just so we can re-use the logic from slack_usergroups
    slack_map: SlackMap = {slack.workspace_name: WorkspaceSpec(slack=slack)}
    slack_usergroups.act(current_state, desired_state, slack_map, dry_run)
