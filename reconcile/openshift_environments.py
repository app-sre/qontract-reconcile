import logging

import reconcile.queries as queries

from reconcile import mr_client_gateway
from utils.mr import CreateEnvironment


QONTRACT_INTEGRATION = 'openshift-environments'


def run(dry_run, gitlab_project_id):
    environments = queries.get_environments()
    target_environments = [e for e in environments if e.get('copy')]

    dir_prefix = 'data'
    actions = []

    for target_environment in target_environments:
        target_environment_name = target_environment['name']
        target_namespaces = target_environment['namespaces']
        target_environment_copy = target_environment['copy']
        target_cluster = target_environment_copy['target']['cluster']
        target_cluster_name = target_cluster['name']
        target_cluster_path = target_cluster['path']
        source_environment = \
            target_environment_copy['source']['environment']
        source_environment_name = source_environment['name']
        source_namespaces = source_environment['namespaces']
        for source_namespace in source_namespaces:
            # collect namespaces to create
            source_namespace_name = source_namespace['name']
            source_namespace_path = source_namespace['path']
            source_cluster = source_namespace['cluster']
            source_cluster_name = source_cluster['name']
            source_cluster_path = source_cluster['path']
            target_namespace_path = \
                source_namespace_path.replace(source_cluster_name,
                                              target_cluster_name)
            if source_namespace_name in target_namespaces:
                continue
            logging.info(['copy_namespace', source_cluster_name,
                          target_cluster_name, source_namespace_name])
            action = {
                'action': 'copy_namespace',
                'source_namespace_path': dir_prefix + source_namespace_path,
                'target_namespace_path': dir_prefix + target_namespace_path,
                'target_cluster_path': target_cluster_path
            }
            actions.append(action)
        # collect saas file targets to create
        saas_files = queries.get_saas_files(env_name=source_environment_name)
        for saas_file in saas_files:
            saas_file_name = saas_file['name']
            saas_file_path = saas_file['path']
            resource_template = saas_file['resourceTemplates']
            for rt in resource_template:
                rt_name = rt['name']
                rt_targets = rt['targets']
                for rt_target in rt_targets:
                    rt_namespace = rt_target['namespace']
                    rt_namespace_name = rt_namespace['name']
                    rt_namespace_path = rt_namespace['path']
                    rt_cluster_name = rt_namespace['cluster']['name']
                    target_namespace_path = \
                        rt_namespace_path.replace(source_cluster_name,
                                                  target_cluster_name)
                    logging.info(['copy_target', saas_file_name,
                                  rt_name, rt_namespace_name])
                    action = {
                        'action': 'copy_target',
                        'saas_file_name': saas_file_path,
                        'rt_name': rt_name,
                        'source_namespace_path': dir_prefix + rt_namespace_path,
                        'target_namespace_path': dir_prefix + target_namespace_path
                    }
                    actions.append(action)

        if not dry_run:
            mr_cli = mr_client_gateway.init(gitlab_project_id=gitlab_project_id,
                                            sqs_or_gitlab='gitlab')
            mr = CreateEnvironment(target_environment_name, actions)
            mr.submit(cli=mr_cli)
