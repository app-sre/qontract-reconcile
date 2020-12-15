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
    try:
        promtool.check_rule(rule['spec'])
    except Exception as e:
        return {'path': rule['path'], 'message': str(e).replace('\n', '')}


def run(dry_run, thread_pool_size=10, cluster_name=None):
    orb.QONTRACT_INTEGRATION = QONTRACT_INTEGRATION
    orb.QONTRACT_INTEGRATION_VERSION = QONTRACT_INTEGRATION_VERSION

    gqlapi = gql.get_api()
    rules_paths = queries.get_prometheus_rules_paths()

    rules = []
    for n in gqlapi.query(orb.NAMESPACES_QUERY)['namespaces']:
        if n['name'] != 'openshift-customer-monitoring':
            continue

        if cluster_name and n['cluster']['name'] != cluster_name:
            continue

        openshift_resources = n.get('openshiftResources')

        for r in openshift_resources:
            if r['path'] not in rules_paths:
                continue

            openshift_resource = orb.fetch_openshift_resource(r, n)
            rules.append({'path': r['path'],
                          'spec': openshift_resource.body['spec']})

    failed = [f for f in threaded.run(check_rule, rules, thread_pool_size)
              if f]

    if failed:
        for f in failed:
            logging.warning(f"Error in rule {f['path']}: {f['message']}")

        sys.exit(1)
