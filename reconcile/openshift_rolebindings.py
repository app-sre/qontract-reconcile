import logging
import sys
import copy

import utils.gql as gql
import utils.threaded as threaded
import reconcile.openshift_base as ob

from utils.aggregated_list import (AggregatedList,
                                   AggregatedDiffRunner,
                                   RunnerException)
from utils.oc import OC_Map
from utils.defer import defer
from utils.openshift_resource import ResourceInventory

NAMESPACES_QUERY = """
{
  namespaces: namespaces_v1 {
    name
    managedRoles
    cluster {
      name
      serverUrl
      jumpHost {
          hostname
          knownHosts
          user
          port
          identity {
              path
              field
              format
          }
      }
      automationToken {
        path
        field
        format
      }
      disable {
        integrations
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
      github_username
    }
    bots {
      github_username
      openshift_serviceaccount
    }
    access {
      namespace {
        name
        cluster {
          name
        }
      }
      role
    }
  }
}
"""

QONTRACT_INTEGRATION = 'openshift-rolebindings'


def get_rolebindings(spec):
    rolebindings = spec.oc.get_items('RoleBinding', namespace=spec.namespace)
    return spec.cluster, spec.namespace, rolebindings


def fetch_current_state(thread_pool_size):
    gqlapi = gql.get_api()
    namespaces = gqlapi.query(NAMESPACES_QUERY)['namespaces']
    state = AggregatedList()
    ri = ResourceInventory()
    namespaces = [namespace_info for namespace_info
                  in namespaces
                  if namespace_info.get('managedRoles')]
    oc_map = OC_Map(namespaces=namespaces, integration=QONTRACT_INTEGRATION)

    state_specs = \
        ob.init_specs_to_fetch(
            ri,
            oc_map,
            namespaces,
            override_managed_types=['RoleBinding']
        )
    results = threaded.run(get_rolebindings, state_specs, thread_pool_size)

    for cluster, namespace, rolebindings in results:
        managed_roles = [namespace_info['managedRoles']
                         for namespace_info in namespaces
                         if namespace_info['cluster']['name'] == cluster
                         and namespace_info['name'] == namespace][0]
        for role in managed_roles:

            users = [
                subject['name']
                for rolebinding in rolebindings
                for subject in rolebinding['subjects']
                if subject['kind'] == 'User' and
                rolebinding['roleRef']['name'] == role
            ]

            state.add({
                "cluster": cluster,
                "namespace": namespace,
                "role": role,
                "kind": 'User',
            }, users)

            bots = [
                subject['namespace'] + '/' + subject['name']
                for rolebinding in rolebindings
                for subject in rolebinding['subjects']
                if subject['kind'] == 'ServiceAccount' and
                'namespace' in subject and
                rolebinding['roleRef']['name'] == role
            ]

            state.add({
                "cluster": cluster,
                "namespace": namespace,
                "role": role,
                "kind": 'ServiceAccount'
            }, bots)

    return oc_map, state


def fetch_desired_state(oc_map):
    gqlapi = gql.get_api()
    roles = gqlapi.query(ROLES_QUERY)['roles']
    state = AggregatedList()

    for role in roles:
        permissions = [{'cluster': a['namespace']['cluster']['name'],
                        'namespace': a['namespace']['name'],
                        'role': a['role']}
                       for a in role['access'] or []
                       if None not in [a['namespace'], a['role']]]
        if not permissions:
            continue
        permissions = [p for p in permissions
                       if p['cluster'] in oc_map.clusters()]

        users = []
        service_accounts = []

        for user in role['users']:
            users.append(user['github_username'])

        for bot in role['bots']:
            if bot['github_username'] is not None:
                users.append(bot['github_username'])
            if bot['openshift_serviceaccount'] is not None:
                service_accounts.append(bot['openshift_serviceaccount'])

        permissions_users = permissions_kind(permissions, u'User')
        list(map(lambda p: state.add(p, users), permissions_users))

        permissions_sas = permissions_kind(permissions, u'ServiceAccount')
        list(map(lambda p: state.add(p, service_accounts), permissions_sas))

    return state


def permissions_kind(permissions, kind):
    permissions_copy = copy.deepcopy(permissions)
    for permission in permissions_copy:
        permission['kind'] = kind
    return permissions_copy


class RunnerAction(object):
    def __init__(self, dry_run, oc_map):
        self.dry_run = dry_run
        self.oc_map = oc_map

    def manage_role(self, label, method_name):
        def action(params, items):
            if len(items) == 0:
                return True

            status = True

            cluster = params['cluster']
            namespace = params['namespace']
            role = params['role']
            kind = params['kind']

            if not self.dry_run:
                oc = self.oc_map.get(cluster)

            for member in items:
                logging.info([
                    label,
                    cluster,
                    namespace,
                    role,
                    kind,
                    member
                ])

                if not self.dry_run:
                    f = getattr(oc, method_name)
                    try:
                        f(namespace, role, member, kind)
                    except Exception as e:
                        logging.error(str(e))
                        status = False

            return status

        return action

    def add_role(self):
        return self.manage_role('add_role', 'add_role_to_user')

    def del_role(self):
        return self.manage_role('del_role', 'remove_role_from_user')


@defer
def run(dry_run=False, thread_pool_size=10, defer=None):
    oc_map, current_state = fetch_current_state(thread_pool_size)
    defer(lambda: oc_map.cleanup())
    desired_state = fetch_desired_state(oc_map)

    # calculate diff
    diff = current_state.diff(desired_state)

    # Ensure all namespace/roles are well known.
    # Any item that appears in `diff['insert']` means that it's not listed
    # as a managedCluster in the cluster datafile.
    if len(diff['insert']) > 0:
        unknown_combinations = [
            "- {}/{}/{}".format(
                item["params"]["cluster"],
                item["params"]["namespace"],
                item["params"]["role"],
            )
            for item in diff['insert']
        ]

        raise RunnerException((
                "Unknown cluster/namespace/combinations found:\n"
                "{}"
            ).format("\n".join(unknown_combinations))
        )

    # Run actions
    runner_action = RunnerAction(dry_run, oc_map)
    runner = AggregatedDiffRunner(diff)

    runner.register("update-insert", runner_action.add_role())
    runner.register("update-delete", runner_action.del_role())
    runner.register("delete", runner_action.del_role())

    status = runner.run()

    if status is False:
        sys.exit(1)
