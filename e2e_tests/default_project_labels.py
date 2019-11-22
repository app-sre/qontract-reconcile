import re
import logging

import e2e_tests.test_base as tb

from utils.defer import defer

QONTRACT_E2E_TEST = 'default-project-labels'


@defer
def run(defer=None):
    oc_map = tb.get_oc_map(QONTRACT_E2E_TEST)
    defer(lambda: oc_map.cleanup())
    pattern = tb.get_namespaces_pattern()
    for cluster in oc_map.clusters():
        oc = oc_map.get(cluster)
        logging.info("[{}] validating default Project labels".format(cluster))

        projects = [p for p in oc.get_all('Project')['items']
                    if p['status']['phase'] != 'Terminating' and
                    not re.search(pattern, p['metadata']['name']) and
                    'api.openshift.com/id'
                    not in p['metadata'].get('labels', {})]

        for project in projects:
            logging.info("[{}/{}] validating default Project labels".format(
                cluster, project['metadata']['name']))
            if project['metadata'].get('labels'):
                assert project['metadata']['labels']['name'] == \
                    project['metadata']['name']
                monitoring_label = "openshift.io/workload-monitoring"
                assert project['metadata']['labels'][monitoring_label] == "true"
