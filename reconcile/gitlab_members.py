import sys
import logging

import utils.gql as gql
from utils.config import get_config
from utils.gitlab_api import GitLabApi

GROUPS_QUERY = """
{
  gitlabgroups_v1{
    managedGroups
  }
}
"""

USERS_QUERY = """
{
  users_v1{
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

def get_groups():
  groups = gqlapi.query(GROUPS_QUERY)
  group_dict = {}
  for g in groups:
    group_dict[g] = []
  return group_dict

def test():
    groups = gqlapi.query(GROUPS_QUERY)
    users = gqlapi.query(USERS_QUERY)
    print(groups)
    print(users)

def get_desired_state():
    groups = gqlapi.query(GROUPS_QUERY)
    users = gqlapi.query(USERS_QUERY)
    desired_group_members = get_groups()
    for g in groups:
      for u in users:
        for r in u['roles']:
          for p in r['permissions']:
            if p['group'] == g:
              desired_group_members[g].append(u['redhat_username']) #redhat_username == gitlab username ??? 
  return desired_group_members


def get_current_state():
    groups = gqlapi.query(GROUPS_QUERY)
    current_group_members = get_groups()
    for g in groups:
      current_group_members[g]=[get_gitlab_group_members(g)]
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
      s_group = subtract_state[f_group] #assumming groups are the same in both states which is a bad assumption
      for f_user in f_group:
        found = False
        for s_user in s_group:
          if f_user != s_user:
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



def run(dry_run=False):
  desired_state = get_desired_state()
  current_state = get_current_state()
  diffs = calculate_diff(current_state,desired_state)

  for diff in diffs:
    logging.info(diff.values())
