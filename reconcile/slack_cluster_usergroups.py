import logging

import reconcile.queries as queries
import reconcile.openshift_users as openshift_users
import reconcile.slack_usergroups as slack_usergroups

from reconcile.slack_base import init_slack_workspace
from utils.slack_api import UsergroupNotFoundException

QONTRACT_INTEGRATION = 'slack-cluster-usergroups'


def get_desired_state(slack):
    desired_state = []
    all_users = queries.get_users()
    all_clusters = queries.get_clusters(minimal=True)
    clusters = [c for c in all_clusters
                if c.get('auth') and c['auth'].get('team')
                and c.get('ocm')]
    openshift_users_desired_state = \
        openshift_users.fetch_desired_state(oc_map=None)
    for cluster in clusters:
        cluster_name = cluster['name']
        cluster_users = [u['user'] for u in openshift_users_desired_state
                         if u['cluster'] == cluster_name]
        usergroup = cluster['auth']['team']
        try:
            ugid = slack.get_usergroup_id(usergroup)
        except UsergroupNotFoundException:
            logging.warning(f'Usergroup {usergroup} not found')
            continue
        user_names = [slack_usergroups.get_slack_username(u) for u in all_users
                      if u['github_username'] in cluster_users
                      and u.get('tag_on_cluster_updates') is not False]
        users = slack.get_users_by_names(user_names)
        channels = slack.get_channels_by_names([slack.chat_kwargs['channel']])
        desired_state.append({
            "workspace": slack.workspace_name,
            "usergroup": usergroup,
            "usergroup_id": ugid,
            "users": users,
            "channels": channels,
            "description": f'Users with access to the {cluster_name} cluster',
        })

    return desired_state


def get_current_state(slack, usergroups):
    current_state = []

    for ug in usergroups:
        users, channels, description = slack.describe_usergroup(ug)
        current_state.append({
            "workspace": slack.workspace_name,
            "usergroup": ug,
            "users": users,
            "channels": channels,
            "description": description,
        })

    return current_state


def run(dry_run):
    slack = init_slack_workspace(QONTRACT_INTEGRATION)
    desired_state = get_desired_state(slack)
    usergroups = [d['usergroup'] for d in desired_state]
    current_state = get_current_state(slack, usergroups)
    slack_usergroups.print_diff(current_state, desired_state)

    if not dry_run:
        # just so we can re-use the logic from slack_usergroups
        slack_map = {slack.workspace_name: {'slack': slack}}
        slack_usergroups.act(desired_state, slack_map)
