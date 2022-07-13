import logging

from reconcile import queries
from reconcile import openshift_users
from reconcile import slack_usergroups

from reconcile.slack_base import slackapi_from_queries
from reconcile.utils.slack_api import UsergroupNotFoundException

QONTRACT_INTEGRATION = "slack-cluster-usergroups"


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


def get_desired_state(slack):
    """
    Get the desired state of the Slack cluster usergroups.

    :param slack: client for calling Slack API
    :type slack: reconcile.utils.slack_api.SlackApi

    :return: desired state data, keys are workspace -> usergroup
                (ex. state['coreos']['app-sre-ic']
    :rtype: dict
    """
    desired_state = {}
    all_users = queries.get_roles(
        sendgrid=False, saas_files=False, aws=False, permissions=False
    )
    all_clusters = queries.get_clusters(minimal=True)
    clusters = [
        c
        for c in all_clusters
        if c.get("auth") and c["auth"].get("team") and c.get("ocm")
    ]
    openshift_users_desired_state = openshift_users.fetch_desired_state(oc_map=None)
    for cluster in clusters:
        cluster_name = cluster["name"]
        cluster_users = [
            u["user"]
            for u in openshift_users_desired_state
            if u["cluster"] == cluster_name
        ]
        usergroup = cluster["auth"]["team"]
        try:
            ugid = slack.get_usergroup_id(usergroup)
        except UsergroupNotFoundException:
            logging.warning(f"Usergroup {usergroup} not found")
            continue
        user_names = [
            slack_usergroups.get_slack_username(u)
            for u in all_users
            if include_user(u, cluster_name, cluster_users)
        ]
        users = slack.get_users_by_names(user_names)
        channels = slack.get_channels_by_names([slack.channel])
        desired_state.setdefault(slack.workspace_name, {})[usergroup] = {
            "workspace": slack.workspace_name,
            "usergroup": usergroup,
            "usergroup_id": ugid,
            "users": users,
            "channels": channels,
            "description": f"Users with access to the {cluster_name} cluster",
        }

    return desired_state


def get_current_state(slack, usergroups):
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
    current_state = {}

    for ug in usergroups:
        users, channels, description = slack.describe_usergroup(ug)
        current_state.setdefault(slack.workspace_name, {})[ug] = {
            "workspace": slack.workspace_name,
            "usergroup": ug,
            "users": users,
            "channels": channels,
            "description": description,
        }

    return current_state


def run(dry_run):
    slack = slackapi_from_queries(QONTRACT_INTEGRATION)
    desired_state = get_desired_state(slack)
    usergroups = []
    for _, workspace_state in desired_state.items():
        for usergroup, _ in workspace_state.items():
            usergroups.append(usergroup)
    current_state = get_current_state(slack, usergroups)

    # just so we can re-use the logic from slack_usergroups
    slack_map = {slack.workspace_name: {"slack": slack}}
    slack_usergroups.act(current_state, desired_state, slack_map, dry_run)
