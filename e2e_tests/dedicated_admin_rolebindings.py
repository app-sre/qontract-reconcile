import re
import logging

import e2e_tests.test_base as tb
import e2e_tests.dedicated_admin_test_base as dat


def run():
    oc_map = tb.get_oc_map()
    pattern = \
        r'^(default|logging|' + \
        '(openshift|kube-|ops-|dedicated-|management-|{}).*)$'.format(
            tb.E2E_NS_PFX
        )
    for cluster, oc in oc_map.items():
        logging.info("[{}] validating RoleBindings".format(cluster))

        projects = [p['metadata']['name']
                    for p in oc.get_all('Project')['items']
                    if p['status']['phase'] != 'Terminating' and
                    not re.search(pattern, p['metadata']['name'])]

        all_rolebindings = \
            oc.get_all('RoleBinding', all_namespaces=True)['items']
        rolebindings = [rb for rb in all_rolebindings
                        if rb['metadata']['namespace'] in projects
                        and rb['groupNames'] == \
                            dat.get_dedicated_admin_groups()
                        and rb['roleRef']['name'] in dat.get_expected_roles()]

        for project in projects:
            logging.info("[{}/{}] validating RoleBindings".format(
                cluster, project))
            project_rbs = [rb for rb in rolebindings
                           if rb['metadata']['namespace'] == project]
            assert len(project_rbs) == 2
            assert project_rbs[0]['roleRef']['name'] != \
                project_rbs[1]['roleRef']['name']
