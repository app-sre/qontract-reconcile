import logging

from reconcile import queries
from reconcile.utils import (
    expiration,
    gql,
)
from reconcile.utils.jenkins_api import JenkinsApi
from reconcile.utils.secret_reader import SecretReader

PERMISSIONS_QUERY = """
{
  permissions: permissions_v1 {
    service
    ...on PermissionJenkinsRole_v1 {
      role
      instance {
        name
        token {
          path
          field
          version
          format
        }
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
      org_username
    }
    bots {
      org_username
    }
    permissions {
      service
      ...on PermissionJenkinsRole_v1 {
        role
        instance {
          name
        }
      }
    }
    expirationDate
  }
}
"""

QONTRACT_INTEGRATION = "jenkins-roles"


def get_jenkins_map() -> dict[str, JenkinsApi]:
    gqlapi = gql.get_api()
    permissions = gqlapi.query(PERMISSIONS_QUERY)["permissions"]
    secret_reader = SecretReader(queries.get_secret_reader_settings())

    jenkins_permissions = [p for p in permissions if p["service"] == "jenkins-role"]

    jenkins_map = {}
    for jp in jenkins_permissions:
        instance = jp["instance"]
        instance_name = instance["name"]
        if instance_name in jenkins_map:
            continue

        token = instance["token"]
        jenkins = JenkinsApi.init_jenkins_from_secret(secret_reader, token)
        jenkins_map[instance_name] = jenkins

    return jenkins_map


def get_current_state(jenkins_map):
    current_state = []

    for instance, jenkins in jenkins_map.items():
        roles = jenkins.get_all_roles()
        for role_name, users in roles.items():
            if role_name == "anonymous":
                continue

            for user in users:
                current_state.append({
                    "instance": instance,
                    "role": role_name,
                    "user": user,
                })

    return current_state


def get_desired_state():
    gqlapi = gql.get_api()
    roles: list[dict] = expiration.filter(gqlapi.query(ROLES_QUERY)["roles"])

    desired_state = []
    for r in roles:
        for p in r["permissions"]:
            if p["service"] != "jenkins-role":
                continue

            for u in r["users"]:
                desired_state.append({
                    "instance": p["instance"]["name"],
                    "role": p["role"],
                    "user": u["org_username"],
                })
            for u in r["bots"]:
                if u["org_username"] is None:
                    continue

                desired_state.append({
                    "instance": p["instance"]["name"],
                    "role": p["role"],
                    "user": u["org_username"],
                })

    return desired_state


def calculate_diff(current_state, desired_state):
    diff = []
    users_to_assign = subtract_states(
        desired_state, current_state, "assign_role_to_user"
    )
    diff.extend(users_to_assign)
    users_to_unassign = subtract_states(
        current_state, desired_state, "unassign_role_from_user"
    )
    diff.extend(users_to_unassign)

    return diff


def subtract_states(from_state, subtract_state, action):
    result = []

    for f_user in from_state:
        found = False
        for s_user in subtract_state:
            if f_user != s_user:
                continue
            found = True
            break
        if not found:
            result.append({
                "action": action,
                "instance": f_user["instance"],
                "role": f_user["role"],
                "user": f_user["user"],
            })

    return result


def act(diff, jenkins_map):
    instance = diff["instance"]
    role = diff["role"]
    user = diff["user"]
    action = diff["action"]

    if action == "assign_role_to_user":
        jenkins_map[instance].assign_role_to_user(role, user)
    elif action == "unassign_role_from_user":
        jenkins_map[instance].unassign_role_from_user(role, user)
    else:
        raise Exception("invalid action: {}".format(action))


def run(dry_run):
    jenkins_map = get_jenkins_map()
    current_state = get_current_state(jenkins_map)
    desired_state = get_desired_state()
    diffs = calculate_diff(current_state, desired_state)

    for diff in diffs:
        logging.info(list(diff.values()))

        if not dry_run:
            act(diff, jenkins_map)
