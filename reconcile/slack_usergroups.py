import logging
import anymarkup
import requests

from sretoolbox.utils import retry

from reconcile import queries
from utils import gql
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
      name
      org_username
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
          escalationPolicyID
        }
        github_owners
        gitlab_owners
        channels
        description
        github_owners_aliases
        gitlab_owners_aliases
      }
    }
  }
}
"""


def get_permissions():
    gqlapi = gql.get_api()
    permissions = gqlapi.query(PERMISSIONS_QUERY)['permissions']

    return [p for p in permissions if p['service'] == 'slack-usergroup']


def get_slack_map():
    settings = queries.get_app_interface_settings()
    permissions = get_permissions()
    slack_map = {}
    for sp in permissions:
        workspace = sp['workspace']
        workspace_name = workspace['name']
        if workspace_name in slack_map:
            continue

        workspace_spec = {
            "slack": SlackApi(workspace['token'], settings=settings),
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
            users, channels, description = slack.describe_usergroup(ug)
            current_state.append({
                "workspace": workspace,
                "usergroup": ug,
                "users": users,
                "channels": channels,
                "description": description,
            })

    return current_state


def get_slack_username(user):
    return user['slack_username'] or user['org_username']


def get_pagerduty_name(user):
    return user['pagerduty_name'] or user['name']


def get_slack_usernames_from_pagerduty(pagerduties, users, usergroup):
    settings = queries.get_app_interface_settings()
    all_slack_usernames = []
    all_pagerduty_names = [get_pagerduty_name(u) for u in users]
    for pagerduty in pagerduties or []:
        pd_token = pagerduty['token']
        pd_schedule_id = pagerduty['scheduleID']
        if pd_schedule_id is not None:
            pd_resource_type = 'schedule'
            pd_resource_id = pd_schedule_id
        pd_escalation_policy_id = pagerduty['escalationPolicyID']
        if pd_escalation_policy_id is not None:
            pd_resource_type = 'escalationPolicy'
            pd_resource_id = pd_escalation_policy_id

        pd = PagerDutyApi(pd_token, settings=settings)
        pagerduty_names = pd.get_pagerduty_users(pd_resource_type,
                                                 pd_resource_id)
        if not pagerduty_names:
            continue
        slack_usernames = [get_slack_username(u)
                           for u in users
                           if get_pagerduty_name(u)
                           in pagerduty_names]
        not_found_pagerduty_names = \
            [pagerduty_name for pagerduty_name in pagerduty_names
             if pagerduty_name not in all_pagerduty_names]
        if not_found_pagerduty_names:
            msg = (
                '[{}] PagerDuty names not found in app-interface: {} '
                '(hint: user files should contain '
                'pagerduty_name if it is different then name)'
            ).format(usergroup, not_found_pagerduty_names)
            logging.warning(msg)
        all_slack_usernames.extend(slack_usernames)

    return all_slack_usernames


def get_slack_usernames_from_github_owners(github_owners,
                                           github_owners_aliases, users,
                                           usergroup):
    return get_slack_usernames_from_owners(
        github_owners, github_owners_aliases, users, usergroup,
        'github_username', missing_user_log_method=logging.debug)


def get_slack_usernames_from_gitlab_owners(gitlab_owners,
                                           gitlab_owners_aliases, users,
                                           usergroup):
    return get_slack_usernames_from_owners(
        gitlab_owners, gitlab_owners_aliases, users, usergroup,
        'org_username', ssl_verify=False)


def get_slack_usernames_from_owners(owners_raw_urls, owners_aliases_raw_url,
                                    users, usergroup, user_key,
                                    ssl_verify=True,
                                    missing_user_log_method=logging.warning):
    all_slack_usernames = []
    all_username_keys = [u[user_key] for u in users]

    owners_aliases = {}
    if owners_aliases_raw_url:
        r = get_raw_owners_content(owners_aliases_raw_url,
                                   ssl_verify=ssl_verify)
        try:
            content = anymarkup.parse(r.content, force_types=None)
            owners_aliases = content['aliases']
        except (anymarkup.AnyMarkupError, KeyError):
            msg = "Could not parse data. Skipping owners_aliases file: {}"
            logging.warning(msg.format(owners_aliases_raw_url))

    for owners_raw_url in owners_raw_urls or []:
        r = get_raw_owners_content(owners_raw_url, ssl_verify=ssl_verify)
        try:
            content = anymarkup.parse(r.content, force_types=None)
            owners = set()
            for value in content.values():
                for user in value:
                    if user in owners_aliases:
                        for alias_user in owners_aliases[user]:
                            owners.add(alias_user)
                    else:
                        owners.add(user)
        except (anymarkup.AnyMarkupError, KeyError):
            msg = "Could not parse data. Skipping owners file: {}"
            logging.warning(msg.format(owners_raw_url))
            continue

        if not owners:
            continue

        slack_usernames = [get_slack_username(u)
                           for u in users
                           if u[user_key]
                           in owners]
        not_found_users = [owner for owner in owners
                           if owner not in all_username_keys]
        if not_found_users:
            msg = f'[{usergroup}] {user_key} not found in app-interface: ' + \
                f'{not_found_users}'
            missing_user_log_method(msg)
        all_slack_usernames.extend(slack_usernames)

    return all_slack_usernames


@retry()
def get_raw_owners_content(owners_raw_url, ssl_verify):
    return requests.get(owners_raw_url, verify=ssl_verify)


def get_desired_state(slack_map):
    gqlapi = gql.get_api()
    roles = gqlapi.query(ROLES_QUERY)['roles']
    all_users = queries.get_users()

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
            description = p['description']
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
            user_names = [get_slack_username(u) for u in r['users']]

            slack_usernames_pagerduty = \
                get_slack_usernames_from_pagerduty(p['pagerduty'],
                                                   all_users, usergroup)
            user_names.extend(slack_usernames_pagerduty)

            slack_usernames_github = get_slack_usernames_from_github_owners(
                    p['github_owners'], p['github_owners_aliases'],
                    all_users, usergroup)
            user_names.extend(slack_usernames_github)

            slack_usernames_gitlab = get_slack_usernames_from_gitlab_owners(
                    p['gitlab_owners'], p['gitlab_owners_aliases'],
                    all_users, usergroup)
            user_names.extend(slack_usernames_gitlab)

            users = slack.get_users_by_names(user_names)

            channel_names = [] if p['channels'] is None else p['channels']
            channels = slack.get_channels_by_names(channel_names)

            desired_state.append({
                "workspace": workspace_name,
                "usergroup": usergroup,
                "usergroup_id": ugid,
                "users": users,
                "channels": channels,
                "description": description,
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

        if d_state['description'] != c_state['description']:
            logging.info(['update_usergroup_description',
                          workspace, usergroup, d_state['description']])


def subtract_state(from_state, subtract_state, type):
    f = from_state[type]
    s = subtract_state[type]
    return [v for k, v in f.items() if k not in s.keys()]


def act(desired_state, slack_map):
    for state in desired_state:
        workspace = state['workspace']
        ugid = state['usergroup_id']
        description = state['description']
        users = state['users'].keys()
        channels = state['channels'].keys()
        slack = slack_map[workspace]['slack']
        slack.update_usergroup_users(ugid, users)
        slack.update_usergroup(ugid, channels, description)


def run(dry_run=False):
    slack_map = get_slack_map()
    current_state = get_current_state(slack_map)
    desired_state = get_desired_state(slack_map)

    print_diff(current_state, desired_state)

    if not dry_run:
        act(desired_state, slack_map)
