import sys
import logging

import utils.gql as gql
from utils.config import get_config
from utils.gitlab_api import GitLabApi

GROUPS_QUERY = """
{
    groups: gitlabgroups_v1{
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
                ... on PermissionGitlabGroups_v1{
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


def get_groups():
    gqlapi = gql.get_api()
    groups = gqlapi.query(GROUPS_QUERY)['groups']
    group_dict = {}
    for g in groups[0]['managedGroups']:
        group_dict[g] = []
    return group_dict

def get_desired_state():
    gqlapi = gql.get_api()
    gl = get_gitlab_api()
    groups = gqlapi.query(GROUPS_QUERY)['groups']
    users = gqlapi.query(USERS_QUERY)['users']
    desired_group_members = get_groups()
    for g in groups[0]['managedGroups']:
        for u in users:
            for r in u['roles']:
                for p in r['permissions']:
                    if 'group' in p and p['group'] == g:
                        desired_group_members[g].append(gl.get_user(u['redhat_username'])) #does redhat_username == gitlab username? this should also account for if user was deleted
        desired_group_members[g].append(gl.get_user('devtools-bot'))
    return desired_group_members


def get_current_state():
    gqlapi = gql.get_api()
    gl = get_gitlab_api()
    groups = gqlapi.query(GROUPS_QUERY)['groups']
    current_group_members = get_groups()
    for g in groups[0]['managedGroups']:
        current_group_members[g]=gl.get_gitlab_group_members(g)
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
    for f_group in from_state:
        s_group = subtract_state[f_group] #assumming groups are the same in both states which is a bad assumption (ex: groups can be deleted)
        for f_user in from_state[f_group]:
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

def act(diff):
    group = diff['group']
    username = diff['user']
    action = diff['action']
    gl = get_gitlab_api()
    if action == "remove_user_from_group":
        gl.remove_group_member(group,username)
    if action == "add_user_to_group":
        gl.add_group_member(group,username)


def run(dry_run=False):
    desired_state = get_desired_state()
    current_state = get_current_state()
    diffs = calculate_diff(current_state,desired_state)
    
    for diff in diffs:
        logging.info(diff.values())
        
        if not dry_run:
            act(diff)
