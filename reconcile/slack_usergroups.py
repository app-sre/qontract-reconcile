import logging

import utils.gql as gql

from utils.slack_api import SlackApi
from utils.pagerduty_api import PagerDutyApi


PERMISSIONS_QUERY = """
{
  permissions: permissions_v1 {
    service
    ...on PermissionSlackUsergroup_v1 {
      handle
      workspace {
        name
        token {
          path
          field
        }
        managedUsergroups
      }
    }
  }
}
"""

ROLES_QUERY = """
{
  roles: roles_v1 {
    name
    users {
      slack_username
      pagerduty_name
    }
    permissions {
      service
      ...on PermissionSlackUsergroup_v1 {
        handle
        workspace {
          name
          managedUsergroups
        }
        pagerduty {
          name
          token {
            path
            field
          }
          scheduleID
        }
        channels
      }
    }
  }
}
"""

USERS_QUERY = """
{
  users: users_v1 {
    slack_username
    pagerduty_name
  }
}
"""


def get_permissions():
    gqlapi = gql.get_api()
    permissions = gqlapi.query(PERMISSIONS_QUERY)['permissions']

    return [p for p in permissions if p['service'] == 'slack-usergroup']


def get_slack_map():
    permissions = get_permissions()
    slack_map = {}
    for sp in permissions:
        workspace = sp['workspace']
        workspace_name = workspace['name']
        if workspace_name in slack_map:
            continue

        workspace_spec = {
            "slack": SlackApi(workspace['token']),
            "managed_usergroups": workspace['managedUsergroups']
        }
        slack_map[workspace_name] = workspace_spec

    return slack_map


def get_current_state(slack_map):
    current_state = []

    for workspace, spec in slack_map.items():
        slack = spec['slack']
        managed_usergroups = spec['managed_usergroups']
        for ug in managed_usergroups:
            users, channels = slack.describe_usergroup(ug)
            current_state.append({
                "workspace": workspace,
                "usergroup": ug,
                "users": users,
                "channels": channels,
            })

    return current_state


def get_slack_username_from_pagerduty(pagerduty, users):
    if pagerduty is None:
        return None

    pd_token = pagerduty['token']
    pd_schedule_id = pagerduty['scheduleID']
    pd = PagerDutyApi(pd_token)
    pagerduty_name = pd.get_final_schedule(pd_schedule_id)
    slack_username = [u['slack_username']
                      for u in users
                      if u['pagerduty_name'] == pagerduty_name]
    if len(slack_username) != 1:
        return None

    [slack_username] = slack_username
    return slack_username


def get_desired_state(slack_map):
    gqlapi = gql.get_api()
    roles = gqlapi.query(ROLES_QUERY)['roles']
    all_users = gqlapi.query(USERS_QUERY)['users']

    desired_state = []
    for r in roles:
        for p in r['permissions']:
            if p['service'] != 'slack-usergroup':
                continue

            workspace = p['workspace']
            managed_usergroups = workspace['managedUsergroups']
            if managed_usergroups is None:
                continue

            workspace_name = workspace['name']
            usergroup = p['handle']
            if usergroup not in managed_usergroups:
                logging.warning(
                    '[{}] usergroup {} not in managed usergroups {}'.format(
                        workspace_name,
                        usergroup,
                        managed_usergroups
                    ))
                continue

            slack = slack_map[workspace_name]['slack']
            ugid = slack.get_usergroup_id(usergroup)
            users_names = [u['slack_username'] for u in r['users']]

            slack_username = \
                get_slack_username_from_pagerduty(p['pagerduty'], all_users)
            if slack_username is not None:
                users_names.append(slack_username)

            users = slack.get_users_by_names(users_names)

            channel_names = [] if p['channels'] is None else p['channels']
            channels = slack.get_channels_by_names(channel_names)

            desired_state.append({
                "workspace": workspace_name,
                "usergroup": usergroup,
                "usergroup_id": ugid,
                "users": users,
                "channels": channels,
            })

    return desired_state


def print_diff(current_state, desired_state):
    for d_state in desired_state:
        workspace = d_state['workspace']
        usergroup = d_state['usergroup']
        c_state = [c for c in current_state
                   if c['workspace'] == workspace
                   and c['usergroup'] == usergroup]
        # at this point we have a single current state item
        # thanks to the logic in get_desired_state
        [c_state] = c_state

        channels_to_add = subtract_state(d_state, c_state, 'channels')
        for c in channels_to_add:
            logging.info(['add_channel_to_usergroup',
                          workspace, usergroup, c])

        channels_to_del = subtract_state(c_state, d_state, 'channels')
        for c in channels_to_del:
            logging.info(['del_channel_from_usergroup',
                          workspace, usergroup, c])

        users_to_add = subtract_state(d_state, c_state, 'users')
        for u in users_to_add:
            logging.info(['add_user_to_usergroup',
                          workspace, usergroup, u])

        users_to_del = subtract_state(c_state, d_state, 'users')
        for u in users_to_del:
            logging.info(['del_user_from_usergroup',
                          workspace, usergroup, u])


def subtract_state(from_state, subtract_state, type):
    f = from_state[type]
    s = subtract_state[type]
    return [v for k, v in f.items() if k not in s.keys()]


def act(desired_state, slack_map):
    for state in desired_state:
        workspace = state['workspace']
        ugid = state['usergroup_id']
        users = state['users'].keys()
        channels = state['channels'].keys()
        slack = slack_map[workspace]['slack']
        slack.update_usergroup_users(ugid, users)
        slack.update_usergroup_channels(ugid, channels)


def run(dry_run=False):
    slack_map = get_slack_map()
    current_state = get_current_state(slack_map)
    desired_state = get_desired_state(slack_map)

    print_diff(current_state, desired_state)

    if not dry_run:
        act(desired_state, slack_map)
