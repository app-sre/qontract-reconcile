import re
import logging

import e2e_tests.test_base as tb
import e2e_tests.dedicated_admin_test_base as dat

from utils.defer import defer

QONTRACT_E2E_TEST = 'dedicated-admin-rolebindings'


@defer
def run(defer=None):
    oc_map = tb.get_oc_map(QONTRACT_E2E_TEST)
    defer(lambda: oc_map.cleanup())
    pattern = \
        r'^(default|logging|' + \
        '(openshift|kube-|ops-|dedicated-|management-|sre-app-check-|' + \
        '{}).*)$'.format(
            tb.E2E_NS_PFX
        )
    for cluster in oc_map.clusters():
        oc = oc_map.get(cluster)
        logging.info("[{}] validating RoleBindings".format(cluster))

        projects = [p['metadata']['name']
                    for p in oc.get_all('Project')['items']
                    if p['status']['phase'] != 'Terminating' and
                    not re.search(pattern, p['metadata']['name']) and
                    'api.openshift.com/id'
                    not in p['metadata'].get('labels', {})]

        all_rolebindings = \
            oc.get_all('RoleBinding', all_namespaces=True)['items']
        rolebindings = [rb for rb in all_rolebindings
                        if rb['metadata']['namespace'] in projects
                        and rb['groupNames'] ==
                        dat.get_dedicated_admin_groups()
                        and rb['roleRef']['name'] in dat.get_expected_roles()]

        for project in projects:
            logging.info("[{}/{}] validating RoleBindings".format(
                cluster, project))
            project_rbs = [rb for rb in rolebindings
                           if rb['metadata']['namespace'] == project]
            roles = {rb['roleRef']['name'] for rb in project_rbs}
            assert len(roles) == 2
            assert 'admin' in roles
