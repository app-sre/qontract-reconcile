import sys
import semver
import logging

import utils.gql as gql
import utils.threaded as threaded
import utils.promtool as promtool
import reconcile.openshift_resources_base as orb
import reconcile.queries as queries

QONTRACT_INTEGRATION = 'prometheus_rules_validator'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


def check_rule(rule):
    rule['check_result'] = promtool.check_rule(rule['spec'])
    return rule


def run(dry_run, thread_pool_size=10, cluster_name=None):
    orb.QONTRACT_INTEGRATION = QONTRACT_INTEGRATION
    orb.QONTRACT_INTEGRATION_VERSION = QONTRACT_INTEGRATION_VERSION

    gqlapi = gql.get_api()
    rules_paths = queries.get_prometheus_rules_paths()

    rules = []
    for n in gqlapi.query(orb.NAMESPACES_QUERY)['namespaces']:
        if cluster_name and n['cluster']['name'] != cluster_name:
            continue

        if not n['managedResourceTypes'] or \
           'PrometheusRule' not in n['managedResourceTypes']:
            continue

        openshift_resources = n.get('openshiftResources')
        if not openshift_resources:
            logging.warning("No openshiftResources defined for namespace"
                            f"{n['name']} in cluster {n['cluster']['name']}")
            continue

        for r in openshift_resources:
            if r['path'] not in rules_paths:
                continue

            openshift_resource = orb.fetch_openshift_resource(r, n)
            rules.append({'path': r['path'],
                          'spec': openshift_resource.body['spec'],
                          'namespace': n['name'],
                          'cluster': n['cluster']['name']})

    failed = [r for r in threaded.run(check_rule, rules, thread_pool_size)
              if not r['check_result']]

    if failed:
        for f in failed:
            logging.warning(f"Error in rule {f['path']} from namespace "
                            f"{f['namespace']} in cluster {f['cluster']}: "
                            f"{f['check_result']}")

        sys.exit(1)
