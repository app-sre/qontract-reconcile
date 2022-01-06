import sys
import datetime
from reconcile.utils import gql
from reconcile import queries
import reconcile.openshift_base as ob
from reconcile.utils import openshift_resource

from reconcile.utils.semver_helper import make_semver
from reconcile.utils.openshift_resource import (OpenshiftResource as OR,
                                                ResourceKeyExistsError)
from reconcile.utils.defer import defer
from reconcile.utils.sharding import is_in_shard

# EXPIRATION_MAX = 90

ROLES_QUERY = """
{
  roles: roles_v1 {
    name
    users {
      github_username
    }
    bots {
      github_username
      openshift_serviceaccount
    }
    access {
      namespace {
        name
        managedRoles
        cluster {
          name
        }
      }
      role
    }
    expirationDate
  }
}
"""


QONTRACT_INTEGRATION = 'openshift-rolebindings'
QONTRACT_INTEGRATION_VERSION = make_semver(0, 3, 0)


def construct_user_oc_resource(role, user):
    name = f"{role}-{user}"
    body = {
        "apiVersion": "authorization.openshift.io/v1",
        "kind": "RoleBinding",
        "metadata": {
            "name": name
        },
        "roleRef": {
            "name": role
        },
        "subjects": [
            {"kind": "User",
             "name": user}
        ]
    }
    return OR(body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION,
              error_details=name), name


def construct_sa_oc_resource(role, namespace, sa_name):
    name = f"{role}-{namespace}-{sa_name}"
    body = {
        "apiVersion": "authorization.openshift.io/v1",
        "kind": "RoleBinding",
        "metadata": {
            "name": name
        },
        "roleRef": {
            "name": role
        },
        "subjects": [
            {"kind": "ServiceAccount",
             "name": sa_name,
             "namespace": namespace}
        ],
        "userNames": [
            f"system:serviceaccount:{namespace}:{sa_name}"
        ]
    }
    return OR(body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION,
              error_details=name), name


def fetch_desired_state(ri, oc_map):
    gqlapi = gql.get_api()
    roles = gqlapi.query(ROLES_QUERY)['roles']
    users_desired_state = []
    for role in roles:
        if not has_valid_expiration_date(role['expirationDate']):
            raise ValueError(
<<<<<<< HEAD
                f'expirationDate field is not formatted as YYYY-MM-DD, '
                f'currently set as {role["expirationDate"]}')
        if not role_still_valid(role):
            raise ValueError(
                f'The maximum expiration date of {role["name"]} '
                f'shall not exceed {EXPIRATION_MAX} \
=======
                f'The maximum expiration date of {role["name"]} '
                f'shall not exceed {openshift_resource.EXPIRATION_MAX} \
>>>>>>> 29a3139 (renaming variable)
                    days from today')
        permissions = [{'cluster': a['namespace']['cluster']['name'],
                        'namespace': a['namespace']['name'],
                        'role': a['role']}
                       for a in role['access'] or []
                       if None not in [a['namespace'], a['role']]
                       and a['namespace'].get('managedRoles')]
        if not permissions:
            continue

        users = [user['github_username']
                 for user in role['users']]
        bot_users = [bot['github_username']
                     for bot in role['bots']
                     if bot.get('github_username')]
        users.extend(bot_users)
        service_accounts = [bot['openshift_serviceaccount']
                            for bot in role['bots']
                            if bot.get('openshift_serviceaccount')]

        for permission in permissions:
            cluster = permission['cluster']
            namespace = permission['namespace']
            if not is_in_shard(f"{cluster}/{namespace}"):
                continue
            if oc_map and not oc_map.get(cluster):
                continue
            for user in users:
                # used by openshift-users and github integrations
                # this is just to simplify things a bit on the their side
                users_desired_state.append({
                    'cluster': cluster,
                    'user': user
                })
                if ri is None:
                    continue
                oc_resource, resource_name = \
                    construct_user_oc_resource(permission['role'], user)
                try:
                    ri.add_desired(
                        cluster,
                        permission['namespace'],
                        'RoleBinding.authorization.openshift.io',
                        resource_name,
                        oc_resource
                    )
                except ResourceKeyExistsError:
                    # a user may have a Role assigned to them
                    # from multiple app-interface roles
                    pass
            for sa in service_accounts:
                if ri is None:
                    continue
                namespace, sa_name = sa.split('/')
                oc_resource, resource_name = \
                    construct_sa_oc_resource(
                        permission['role'], namespace, sa_name)
                try:
                    ri.add_desired(
                        permission['cluster'],
                        permission['namespace'],
                        'RoleBinding.authorization.openshift.io',
                        resource_name,
                        oc_resource
                    )
                except ResourceKeyExistsError:
                    # a ServiceAccount may have a Role assigned to it
                    # from multiple app-interface roles
                    pass

    return users_desired_state


@defer
def run(dry_run, thread_pool_size=10, internal=None,
        use_jump_host=True, defer=None):
    namespaces = [namespace_info for namespace_info
                  in queries.get_namespaces()
                  if namespace_info.get('managedRoles')
                  and is_in_shard(
                      f"{namespace_info['cluster']['name']}/" +
                      f"{namespace_info['name']}")]
    ri, oc_map = ob.fetch_current_state(
        namespaces=namespaces,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        override_managed_types=['RoleBinding.authorization.openshift.io'],
        internal=internal,
        use_jump_host=use_jump_host)
    defer(oc_map.cleanup)
    fetch_desired_state(ri, oc_map)
    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)

    if ri.has_error_registered():
        sys.exit(1)


def has_valid_expiration_date(exp_date):
    date_format = "%Y-%m-%d"
    date_bool = True
    try:
        date_bool = bool(datetime.datetime.strptime(exp_date, date_format))
    except ValueError:
        date_bool = False
    return date_bool


def role_still_valid(role):
    exp_date = datetime.datetime \
        .strptime(role['expirationDate'], '%Y-%m-%d').date()
    if (exp_date - datetime.datetime.utcnow().date()).days <= EXPIRATION_MAX:
        return True
    return False
