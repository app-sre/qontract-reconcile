import logging

from typing import Any

from reconcile.slack_usergroups import get_pagerduty_map, get_usernames_from_pagerduty
from reconcile.utils import gql
from reconcile import queries
from reconcile.utils.gitlab_api import GitLabApi


PERMISSIONS_QUERY = """
{
  permissions: permissions_v1 {
    ... on PermissionGitlabGroupMembership_v1 {
      name
      group
      access
      pagerduty {
        name
        instance {
          name
        }
        scheduleID
        escalationPolicyID
      }
      roles {
        users {
          org_username
        }
        bots {
          org_username
        }
      }
    }
  }
}
"""

QONTRACT_INTEGRATION = "gitlab-members"


def get_current_state(instance, gl):
    return {g: gl.get_group_members(g) for g in instance["managedGroups"]}


def get_permissions():
    gqlapi = gql.get_api()
    return gqlapi.query(PERMISSIONS_QUERY)["permissions"]


def get_desired_state(instance, gl):
    permissions = get_permissions()
    desired_group_members = {g: [] for g in instance["managedGroups"]}
    pagerduty_map = get_pagerduty_map()
    all_users = queries.get_users()
    for g in desired_group_members:
        for p in permissions:
            if "group" in p and p["group"] == g:
                for r in p.get("roles") or []:
                    for u in r.get("users") or []:
                        user = u["org_username"]
                        item = {"user": user, "access_level": p["access"]}
                        desired_group_members[g].append(item)
                    for b in r.get("bots") or []:
                        user = b["org_username"]
                        item = {"user": user, "access_level": p["access"]}
                        desired_group_members[g].append(item)
                pagerduty = p.get("pagerduty")
                if pagerduty:
                    usernames_from_pagerduty = get_usernames_from_pagerduty(
                        pagerduty,
                        all_users,
                        g,
                        pagerduty_map,
                        get_username_method=lambda u: u["org_username"],
                    )
                    for u in usernames_from_pagerduty:
                        item = {"user": u, "access_level": p["access"]}
                        desired_group_members[g].append(item)

    return desired_group_members


def calculate_diff(current_state, desired_state):
    diff = []
    users_to_add = subtract_states(desired_state, current_state, "add_user_to_group")
    diff.extend(users_to_add)
    users_to_remove = subtract_states(
        current_state, desired_state, "remove_user_from_group"
    )
    diff.extend(users_to_remove)
    users_to_change = check_access(desired_state, current_state)
    diff.extend(users_to_change)

    return diff


def subtract_states(from_state, subtract_state, action):
    result = []
    for f_group, f_users in from_state.items():
        s_group = subtract_state[f_group]
        for f_user in f_users:
            found = False
            for s_user in s_group:
                if f_user["user"] != s_user["user"]:
                    continue
                found = True
                break
            if not found:
                result.append(
                    {
                        "action": action,
                        "group": f_group,
                        "user": f_user["user"],
                        "access": f_user["access_level"],
                    }
                )
    return result


def check_access(desired_state, current_state):
    result = []
    for d_group, d_users in desired_state.items():
        c_group = current_state[d_group]
        for d_user in d_users:
            for c_user in c_group:
                if d_user["user"] == c_user["user"]:
                    if d_user["access_level"] != c_user["access_level"]:
                        result.append(
                            {
                                "action": "change_access",
                                "group": d_group,
                                "user": c_user["user"],
                                "access": d_user["access_level"],
                            }
                        )
                    break
    return result


def act(diff, gl):
    group = diff["group"]
    user = diff["user"]
    action = diff["action"]
    access = diff["access"]
    if action == "remove_user_from_group":
        gl.remove_group_member(group, user)
    if action == "add_user_to_group":
        gl.add_group_member(group, user, access)
    if action == "change_access":
        gl.change_access(group, user, access)


def run(dry_run):
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    gl = GitLabApi(instance, settings=settings)
    current_state = get_current_state(instance, gl)
    desired_state = get_desired_state(instance, gl)
    diffs = calculate_diff(current_state, desired_state)

    for diff in diffs:
        logging.info(list(diff.values()))

        if not dry_run:
            act(diff, gl)


def early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
    return {
        "instance": queries.get_gitlab_instance(),
        "permissions": get_permissions(),
    }
