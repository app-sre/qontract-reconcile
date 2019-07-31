import sys
import time
import datetime
import logging

import utils.gql as gql
import reconcile.openshift_resources as openshift_resources

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
    unManaged
    automationToken {
      path
      field
      format
    }
  }
}
"""


def run_create_namespace_test():
    gqlapi = gql.get_api()
    clusters = gqlapi.query(CLUSTERS_QUERY)['clusters']
    oc_map = {}
    error = False

    ns_to_create = 'create-namespace-test-{}'.format(
        datetime.datetime.utcnow().strftime('%Y%m%d%H%M')
    )
    groups = ['dedicated-admins', 'system:serviceaccounts:dedicated-admin']
    expected_rolebindings = [
        {'name': 'admin-0',
         'role': 'admin',
         'groups': groups},
        {'name': 'dedicated-project-admin',
         'role': 'dedicated-project-admin',
         'groups': groups},
    ]
    for cluster_info in clusters:
        cluster = cluster_info['name']
        oc = openshift_resources.obtain_oc_client(oc_map, cluster_info)

        if not oc:
            logging.debug("Skipping {} (no automationToken).".format(cluster))
            continue

        if cluster_info['unManaged']:
            logging.debug("Skipping {} (unmanaged cluster).".format(cluster))
            continue

        logging.info("[{}] Creating namespace {}".format(
            cluster, ns_to_create
        ))

        try:
            oc.new_project(ns_to_create)
            time.sleep(2) #  allow time for RoleBindings to be created
            for expected_rb in expected_rolebindings:
                rb = oc.get(ns_to_create, 'RoleBinding', expected_rb['name'])
                rb_roleref_name = rb['roleRef']['name']
                assert rb_roleref_name == expected_rb['role']
                rb_group_names = rb['groupNames']
                assert rb_group_names == expected_rb['groups']
        finally:
            logging.info("[{}] Deleting namespace {}".format(
                cluster, ns_to_create
            ))
            oc.delete_project(ns_to_create)

    return error


def run():
    error = run_create_namespace_test()
    if error:
        sys.exit(1)
