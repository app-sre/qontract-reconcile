import logging
import sys
import copy

import utils.gql as gql
import utils.vault_client as vault_client

from utils.openshift_api import Openshift
from utils.aggregated_list import (AggregatedList,
                                   AggregatedDiffRunner,
                                   RunnerException)

CLUSTERS_QUERY = """
{
  clusters: clusters_v1 {
    name
    serverUrl
    managedGroups
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
    permissions {
      ...on PermissionOpenshiftGroup_v1 {
        service
        cluster
        group
      }
    }
  }
}
"""


class ClusterStore(object):
    _clusters = {}

    def __init__(self, clusters):
        _clusters = {}

        for cluster_info in clusters:
            cluster_name = cluster_info['name']
            groups = cluster_info['managedGroups']
            jump_host = cluster_info.get('jumpHost')
            automation_token = cluster_info.get('automationToken')

            if not automation_token:
                continue

            if _clusters.get(cluster_name) is not None:
                continue

            if groups is None:
                continue

            token = vault_client.read(
                automation_token['path'],
                automation_token['field'],
            )

            api = Openshift(cluster_info['serverUrl'], token,
                            jump_host=jump_host)

            _clusters[cluster_name] = {
                'api': api,
                'groups': groups
            }

        self._clusters = _clusters

    def clusters(self):
        return self._clusters.keys()

    def api(self, cluster):
        return self._clusters[cluster]['api']

    def groups(self, cluster):
        return self._clusters[cluster]['groups']

    def cleanup(self):
        for cluster in self.clusters():
            api = self.api(cluster)
            api.cleanup()


def fetch_current_state(cluster_store):
    current_state = []

    for cluster in cluster_store.clusters():
        api = cluster_store.api(cluster)

        for group_name in cluster_store.groups(cluster):
            group = api.get_group(group_name)
            for user in group['users']:
                current_state.append({
                    "cluster": cluster,
                    "group": group_name,
                    "user": user
                })

    return current_state


def fetch_desired_state(roles):
    desired_state = []

    for r in roles:
        for p in r['permissions']:
            if 'service' not in p:
                continue
            if p['service'] != 'openshift-group':
                continue

            for u in r['users']:
                if 'github_username' is None:
                    continue

                desired_state.append({
                    "cluster": p['cluster'],
                    "group": p['group'],
                    "user": u['github_username']
                })

    return desired_state


def calculate_diff(current_state, desired_state):
    diff = []

    for d_user in desired_state:
        found = False
        for c_user in current_state:
            if d_user != c_user:
                continue
            found = True
            break
        if not found:
            diff.append([
                "add_user_to_group",
                d_user['cluster'],
                d_user['group'],
                d_user['user']
            ])

    for c_user in current_state:
        found = False
        for d_user in desired_state:
            if c_user != d_user:
                continue
            found = True
            break
        if not found:
            diff.append([
                "del_user_from_group",
                c_user['cluster'],
                c_user['group'],
                c_user['user']
            ])

    return diff


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
            kind = params['kind']

            if not self.dry_run:
                api = self.cluster_store.api(cluster)

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
                    f = getattr(api, method_name)
                    try:
                        f(namespace, role, member, kind)
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

    clusters = gqlapi.query(CLUSTERS_QUERY)['clusters']
    cluster_store = ClusterStore(clusters)
    roles = gqlapi.query(ROLES_QUERY)['roles']

    current_state = fetch_current_state(cluster_store)
    desired_state = fetch_desired_state(roles)
    diffs = calculate_diff(current_state, desired_state)

    for diff in diffs:
        print(diff)
    import sys
    sys.exit()

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
