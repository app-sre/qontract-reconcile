import logging
import sys

import utils.gql as gql
import utils.vault_client as vault_client

from utils.openshift_api import Openshift
from utils.aggregated_list import (AggregatedList,
                                   AggregatedDiffRunner,
                                   RunnerException)

NAMESPACES_QUERY = """
{
  namespaces: namespaces_v1 {
    name
    managedRoles
    cluster {
      name
      serverUrl
      jumpHost
      automationToken {
        path
        field
        format
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
    }
    permissions {
      ...on PermissionOpenshiftRolebinding_v1 {
        service
        cluster
        namespace
        role
      }
    }
  }
}
"""


class ClusterStore(object):
    _clusters = {}

    def __init__(self, namespaces):
        _clusters = {}

        for namespace_info in namespaces:
            namespace_name = namespace_info['name']
            managed_roles = namespace_info.get('managedRoles')
            cluster_info = namespace_info['cluster']
            cluster_name = cluster_info['name']
            jump_host = cluster_info.get('jumpHost')
            automation_token = cluster_info.get('automationToken')

            if not managed_roles or not automation_token:
                continue

            if _clusters.get(cluster_name) is None:
                token = vault_client.read(
                    automation_token['path'],
                    automation_token['field'],
                )

                api = Openshift(cluster_info['serverUrl'], token,
                                jump_host=jump_host)

                _clusters[cluster_name] = {
                    'api': api,
                    'namespaces': {}
                }

            _clusters[cluster_name]['namespaces'][namespace_name] = \
                managed_roles

        self._clusters = _clusters

    def clusters(self):
        return self._clusters.keys()

    def api(self, cluster):
        return self._clusters[cluster]['api']

    def namespaces(self, cluster):
        return self._clusters[cluster]['namespaces'].keys()

    def namespace_managed_roles(self, cluster, namespace):
        return self._clusters[cluster]['namespaces'][namespace]


def fetch_current_state(cluster_store):
    state = AggregatedList()

    for cluster in cluster_store.clusters():
        api = cluster_store.api(cluster)

        for namespace in cluster_store.namespaces(cluster):
            roles = cluster_store.namespace_managed_roles(cluster, namespace)

            for role in roles:
                rolebindings = api.get_rolebindings(namespace, role)

                members = [
                    subject[u'name']
                    for rolebinding in rolebindings
                    for subject in rolebinding['subjects']
                    if subject[u'kind'] == u'User'
                ]

                state.add({
                    "service": "openshift-rolebinding",
                    "cluster": cluster,
                    "namespace": namespace,
                    "role": role,
                }, members)

    return state


def fetch_desired_state(roles):
    state = AggregatedList()

    for role in roles:
        permissions = list(filter(
            lambda p: p.get('service') == 'openshift-rolebinding',
            role['permissions']
        ))

        if permissions:
            members = []

            for user in role['users']:
                members.append(user['github_username'])

            for bot in role['bots']:
                if 'github_username' in bot:
                    members.append(bot['github_username'])

            list(map(lambda p: state.add(p, members), permissions))

    return state


class RunnerAction(object):
    def __init__(self, dry_run, cluster_store):
        self.dry_run = dry_run
        self.cluster_store = cluster_store

    def manage_role(self, label, method_name):
        def action(params, items):
            if len(items) == 0:
                return True

            status = True

            cluster = params['cluster']
            namespace = params['namespace']
            role = params['role']

            if not self.dry_run:
                api = self.cluster_store.api(cluster)

            for member in items:
                logging.info([
                    label,
                    member,
                    cluster,
                    namespace,
                    role
                ])

                if not self.dry_run:
                    f = getattr(api, method_name)
                    try:
                        f(namespace, role, member)
                    except Exception as e:
                        logging.error(e.message)
                        status = False

            return status

        return action

    def add_role(self):
        return self.manage_role('add_role', 'add_role_to_user')

    def del_role(self):
        return self.manage_role('del_role', 'remove_role_from_user')


def run(dry_run=False):
    gqlapi = gql.get_api()

    namespaces = gqlapi.query(NAMESPACES_QUERY)['namespaces']
    roles = gqlapi.query(ROLES_QUERY)['roles']

    cluster_store = ClusterStore(namespaces)

    current_state = fetch_current_state(cluster_store)
    desired_state = fetch_desired_state(roles)

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
    runner_action = RunnerAction(dry_run, cluster_store)
    runner = AggregatedDiffRunner(diff)

    runner.register("update-insert", runner_action.add_role())
    runner.register("update-delete", runner_action.del_role())
    runner.register("delete", runner_action.del_role())

    status = runner.run()

    if status is False:
        sys.exit(1)
