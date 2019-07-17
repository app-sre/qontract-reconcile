import logging

import utils.gql as gql
from utils.config import get_config
from utils.gitlab_api import GitLabApi

GROUPS_QUERY = """
{
  instances: gitlabinstance_v1{
    managedGroups
  }
}
"""

USERS_QUERY = """
{
  users: users_v1{
    redhat_username
      roles{
        permissions{
          ... on PermissionGitlabGroupMembership_v1{
            name
            group
          }
      }
    }
  }
}
"""

BOTS_QUERY = """
{
  bots: bots_v1{
    redhat_username
      roles{
        permissions{
          ... on PermissionGitlabGroupMembership_v1{
            name
            group
        }
      }
    }
  }
}
"""


def get_gitlab_api():
    config = get_config()
    gitlab_config = config['gitlab']
    server = gitlab_config['server']
    token = gitlab_config['token']
    return GitLabApi(server, token, ssl_verify=False)


def create_groups_dict(gqlapi):
    instances = gqlapi.query(GROUPS_QUERY)['instances']
    groups_dict = {}
    for i in instances:
        for g in i['managedGroups']:
            groups_dict[g] = []
    return groups_dict


def get_desired_state(gqlapi, gl):
    users = gqlapi.query(USERS_QUERY)['users']
    bots = gqlapi.query(BOTS_QUERY)['bots']
    desired_group_members = create_groups_dict(gqlapi)
    for g in desired_group_members:
        for u in users:
            for r in u['roles']:
                for p in r['permissions']:
                    if 'group' in p and p['group'] == g:
                        user = gl.get_user(u['redhat_username'])
                        if user is not None:
                            desired_group_members[g].append(user)
        for b in bots:
            for r in b['roles']:
                for p in r['permissions']:
                    if 'group' in p and p['group'] == g:
                        username = b['redhat_username']
                        desired_group_members[g].append(gl.get_user(username))
    return desired_group_members


def get_current_state(gqlapi, gl):
    current_group_members = create_groups_dict(gqlapi)
    for g in current_group_members:
        current_group_members[g] = gl.get_group_members(g)
    return current_group_members


def calculate_diff(current_state, desired_state):
    diff = []
    users_to_add = \
        subtract_states(desired_state, current_state,
                        "add_user_to_group")
    diff.extend(users_to_add)
    users_to_remove = \
        subtract_states(current_state, desired_state,
                        "remove_user_from_group")
    diff.extend(users_to_remove)

    return diff


def subtract_states(from_state, subtract_state, action):
    result = []
    for f_group, f_users in from_state.items():
        s_group = subtract_state[f_group]
        for f_user in f_users:
            found = False
            for s_user in s_group:
                if f_user.id != s_user.id:
                    continue
                found = True
                break
            if not found:
                result.append({
                    "action": action,
                    "group": f_group,
                    "user": f_user,
                })
    return result


def act(diff, gl):
    group = diff['group']
    username = diff['user']
    action = diff['action']
    if action == "remove_user_from_group":
        gl.remove_group_member(group, username)
    if action == "add_user_to_group":
        gl.add_group_member(group, username)


def run(dry_run=False):
    gqlapi = gql.get_api()
    gl = get_gitlab_api()
    current_state = get_current_state(gqlapi, gl)
    desired_state = get_desired_state(gqlapi, gl)
    diffs = calculate_diff(current_state, desired_state)

    for diff in diffs:
        logging.info(diff.values())

        if not dry_run:
            act(diff, gl)
