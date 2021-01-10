import logging

import reconcile.queries as queries

from reconcile.utils.ocm import OCMMap

QONTRACT_INTEGRATION = 'ocm-aws-infrastructure-access'


def fetch_current_state():
    current_state = []
    settings = queries.get_app_interface_settings()
    clusters = [c for c in queries.get_clusters()
                if c.get('ocm') is not None]
    ocm_map = OCMMap(clusters=clusters, integration=QONTRACT_INTEGRATION,
                     settings=settings)

    for cluster_info in clusters:
        cluster = cluster_info['name']
        ocm = ocm_map.get(cluster)
        role_grants = ocm.get_aws_infrastructure_access_role_grants(cluster)
        for user_arn, access_level in role_grants:
            item = {
                'cluster': cluster,
                'user_arn': user_arn,
                'access_level': access_level
            }
            current_state.append(item)

    return ocm_map, current_state


def fetch_desired_state():
    desired_state = []
    clusters = [c for c in queries.get_clusters()
                if c.get('awsInfrastructureAccess') is not None]
    for cluster_info in clusters:
        cluster = cluster_info['name']
        aws_infra_access_items = cluster_info['awsInfrastructureAccess']
        for aws_infra_access in aws_infra_access_items:
            aws_group = aws_infra_access['awsGroup']
            access_level = aws_infra_access['accessLevel']
            aws_account = aws_group['account']
            aws_account_uid = aws_account['uid']
            users = [user['org_username']
                     for role in aws_group['roles']
                     for user in role['users']]

            for user in users:
                item = {
                    'cluster': cluster,
                    'user_arn': f"arn:aws:iam::{aws_account_uid}:user/{user}",
                    'access_level': access_level
                }
                desired_state.append(item)

            # add terraform user account with network management access level
            tf_user = aws_account.get('terraformUsername')
            if tf_user:
                item = {
                    'cluster': cluster,
                    'user_arn':
                        f"arn:aws:iam::{aws_account_uid}:user/{tf_user}",
                    'access_level': 'network-mgmt'
                }
                desired_state.append(item)

    return desired_state


def act(dry_run, ocm_map, current_state, desired_state):
    to_add = [d for d in desired_state if d not in current_state]
    for item in to_add:
        cluster = item['cluster']
        user_arn = item['user_arn']
        access_level = item['access_level']
        logging.info(['add_user_to_aws_infrastructure_access_role_grants',
                      cluster, user_arn, access_level])
        if not dry_run:
            ocm = ocm_map.get(cluster)
            ocm.add_user_to_aws_infrastructure_access_role_grants(
                cluster, user_arn, access_level)
    to_delete = [c for c in current_state if c not in desired_state]
    for item in to_delete:
        cluster = item['cluster']
        user_arn = item['user_arn']
        access_level = item['access_level']
        logging.info(['del_user_from_aws_infrastructure_access_role_grants',
                      cluster, user_arn, access_level])
        if not dry_run:
            ocm = ocm_map.get(cluster)
            ocm.del_user_from_aws_infrastructure_access_role_grants(
                cluster, user_arn, access_level)


def run(dry_run):
    ocm_map, current_state = fetch_current_state()
    desired_state = fetch_desired_state()
    act(dry_run, ocm_map, current_state, desired_state)
