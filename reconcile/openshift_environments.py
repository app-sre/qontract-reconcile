import logging

import reconcile.queries as queries

from utils.defer import defer
from utils.mr import CreateEnvironment


QONTRACT_INTEGRATION = 'openshift-environments'


@defer
def run(dry_run, thread_pool_size=10, internal=None,
        use_jump_host=True, defer=None):
    environments = queries.get_environments()
    target_environments = [e for e in environments if e.get('copy')]

    actions = []

    for target_environment in target_environments:
        target_environment_name = target_environment['name']
        target_namespaces = target_environment['namespaces']
        target_environment_copy = target_environment['copy']
        target_cluster = target_environment_copy['target']['cluster']
        target_cluster_name = target_cluster['name']
        source_environment = \
            target_environment_copy['source']['environment']
        source_environment_name = source_environment['name']
        source_namespaces = source_environment['namespaces']
        for source_namespace in source_namespaces:
            # collect namespaces to create
            source_namespace_name = source_namespace['name']
            if source_namespace_name in target_namespaces:
                continue
            logging.info(['create_namespace', target_cluster_name,
                          source_namespace_name])
            action = {
                'action': 'create_namespace',
                'source_namespace': source_namespace,
                'target_cluster': target_cluster
            }
            actions.append(action)
        # collect saas file targets to create
        saas_files = queries.get_saas_files(env_name=source_environment_name)
        for saas_file in saas_files:
            saas_file_name = saas_file['name']
            resource_template = saas_file['resourceTemplates']
            for rt in resource_template:
                rt_name = rt['name']
                rt_targets = rt['targets']
                for rt_target in rt_targets:
                    rt_namespace = rt_target['namespace']
                    rt_namespace_name = rt_namespace['name']
                    rt_namespace_path = rt_namespace['path']
                    rt_environment_name = rt_namespace['environment']['name']
                    if rt_environment_name != source_environment_name:
                        continue
                    logging.info(['create_target', saas_file_name,
                                    rt_name, rt_namespace_name])
                    action = {
                        'action': 'create_target',
                        'saas_file_name': saas_file_name,
                        'rt_name': rt_name,
                        'target_namespace_path': rt_namespace_path
                    }
                    actions.append(action)

        mr = CreateEnvironment(target_environment_name, actions)
        # mr.submit(cli=mr_cli)
