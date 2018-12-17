import logging

import reconcile.gql as gql
import utils.vault_client as vault_client

from reconcile.aggregated_list import (AggregatedList,
                                       AggregatedDiffRunner,
                                       RunnerException)
from utils.openshift_api import Openshift

CLUSTER_CATALOG_QUERY = """
{
  cluster {
    name
    serverUrl
    automationToken {
      path
      field
      format
    }
    managedRoles {
      namespace
      role
    }
  }
}
"""

ROLEBINDINGS_QUERY = """
{
  role {
    name
    members {
      ...on Bot_v1 {
        schema
        github_username_optional: github_username
      }
      ...on User_v1 {
        schema
        github_username
      }
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

    def __init__(self):
        gqlapi = gql.get_api()
        result = gqlapi.query(CLUSTER_CATALOG_QUERY)

        for cluster_info in result['cluster']:
            name = cluster_info['name']
            automationToken = cluster_info.get('automationToken')

            if not automationToken:
                continue

            token = vault_client.read(
                automationToken['path'],
                automationToken['field'],
            )

            api = Openshift(cluster_info['serverUrl'], token)

            self._clusters[name] = {
                'api': api,
                'managed_roles': cluster_info['managedRoles']
            }

    def clusters(self):
        return self._clusters.keys()

    def api(self, cluster):
        return self._clusters[cluster]['api']

    def namespaces(self, cluster):
        return [
            role['namespace']
            for role in self._clusters[cluster]['managed_roles']
        ]

    def namespace_roles(self, cluster, namespace):
        return [
            managed_role['role']
            for managed_role in self._clusters[cluster]['managed_roles']
            if managed_role['namespace'] == namespace
        ]


def fetch_current_state(cluster_store):
    state = AggregatedList()

    for cluster in cluster_store.clusters():
        api = cluster_store.api(cluster)

        for namespace in cluster_store.namespaces(cluster):
            for role in cluster_store.namespace_roles(cluster, namespace):
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


def fetch_desired_state():
    gqlapi = gql.get_api()
    result = gqlapi.query(ROLEBINDINGS_QUERY)

    state = AggregatedList()

    def username(m):
        if m['schema'] == '/access/bot-1.yml':
            return m.get('github_username_optional')
        else:
            return m['github_username']

    for role in result['role']:
        permissions = list(filter(
            lambda p: p.get('service') == 'openshift-rolebinding',
            role['permissions']
        ))

        if permissions:
            members = [
                member for member in
                (username(m) for m in role['members'])
                if member is not None
            ]

            list(map(lambda p: state.add(p, members), permissions))

    return state


class RunnerAction(object):
    def __init__(self, dry_run, cluster_store):
        self.dry_run = dry_run
        self.cluster_store = cluster_store

    def manage_role(self, label, method_name):
        def action(params, items):
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
                    f(namespace, role, member)

        return action

    def add_role(self):
        return self.manage_role('add_role', 'add_role_to_user')

    def del_role(self):
        return self.manage_role('del_role', 'remove_role_from_user')


def run(dry_run=False):
    cluster_store = ClusterStore()

    current_state = fetch_current_state(cluster_store)
    desired_state = fetch_desired_state()

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

    runner.run()
