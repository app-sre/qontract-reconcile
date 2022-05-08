import logging

from reconcile.utils import gql
from reconcile import queries

from reconcile.utils.ocm import STATUS_DELETING, STATUS_FAILED, OCMMap
from reconcile.terraform_resources import TF_NAMESPACES_QUERY

QONTRACT_INTEGRATION = "ocm-aws-infrastructure-access"


def fetch_current_state():
    current_state = []
    current_failed = []
    current_deleting = []
    settings = queries.get_app_interface_settings()
    clusters = [c for c in queries.get_clusters() if c.get("ocm") is not None]
    ocm_map = OCMMap(
        clusters=clusters, integration=QONTRACT_INTEGRATION, settings=settings
    )

    for cluster_info in clusters:
        cluster = cluster_info["name"]
        ocm = ocm_map.get(cluster)
        role_grants = ocm.get_aws_infrastructure_access_role_grants(cluster)
        for user_arn, access_level, state, _ in role_grants:
            item = {
                "cluster": cluster,
                "user_arn": user_arn,
                "access_level": access_level,
            }
            if state == STATUS_FAILED:
                current_failed.append(item)
            elif state == STATUS_DELETING:
                current_deleting.append(item)
            else:
                current_state.append(item)

    return ocm_map, current_state, current_failed, current_deleting


def fetch_desired_state():
    desired_state = []

    # get desired state defined in awsInfrastructureAccess
    # or awsInfrastructureManagementAccounts
    # sections of cluster files
    clusters = queries.get_clusters()
    for cluster_info in clusters:
        cluster = cluster_info["name"]
        aws_infra_access_items = cluster_info.get("awsInfrastructureAccess") or []
        for aws_infra_access in aws_infra_access_items:
            aws_group = aws_infra_access["awsGroup"]
            access_level = aws_infra_access["accessLevel"]
            aws_account = aws_group["account"]
            aws_account_uid = aws_account["uid"]
            users = [
                user["org_username"]
                for role in aws_group["roles"]
                for user in role["users"]
            ]

            for user in users:
                item = {
                    "cluster": cluster,
                    "user_arn": f"arn:aws:iam::{aws_account_uid}:user/{user}",
                    "access_level": access_level,
                }
                desired_state.append(item)

        aws_infra_management_items = (
            cluster_info.get("awsInfrastructureManagementAccounts") or []
        )
        for aws_infra_management in aws_infra_management_items:
            aws_account = aws_infra_management["account"]
            access_level = aws_infra_management["accessLevel"]
            aws_account_uid = aws_account["uid"]
            # add terraform user account
            tf_user = aws_account.get("terraformUsername")
            if tf_user:
                item = {
                    "cluster": cluster,
                    "user_arn": f"arn:aws:iam::{aws_account_uid}:user/{tf_user}",
                    "access_level": access_level,
                }
                desired_state.append(item)

    # get desired state defined in terraformResources
    # section for aws-iam-service-account resources
    # of namespace files
    aws_accounts = queries.get_aws_accounts()
    gqlapi = gql.get_api()
    namespaces = gqlapi.query(TF_NAMESPACES_QUERY)["namespaces"]
    for namespace_info in namespaces:
        terraform_resources = namespace_info.get("terraformResources") or None
        if terraform_resources is None:
            continue
        for tf_resource in terraform_resources:
            provider = tf_resource["provider"]
            if provider != "aws-iam-service-account":
                continue
            aws_infrastructure_access = (
                tf_resource.get("aws_infrastructure_access") or None
            )
            if aws_infrastructure_access is None:
                continue
            aws_account_uid = [
                a["uid"] for a in aws_accounts if a["name"] == tf_resource["account"]
            ][0]
            user = tf_resource["identifier"]
            cluster = aws_infrastructure_access["cluster"]["name"]
            access_level = aws_infrastructure_access["access_level"]
            item = {
                "cluster": cluster,
                "user_arn": f"arn:aws:iam::{aws_account_uid}:user/{user}",
                "access_level": access_level,
            }
            desired_state.append(item)

    return desired_state


def act(
    dry_run, ocm_map, current_state, current_failed, desired_state, current_deleting
):
    to_delete = [c for c in current_state if c not in desired_state]
    to_delete = to_delete + current_failed
    for item in to_delete:
        cluster = item["cluster"]
        user_arn = item["user_arn"]
        access_level = item["access_level"]
        logging.info(
            [
                "del_user_from_aws_infrastructure_access_role_grants",
                cluster,
                user_arn,
                access_level,
            ]
        )
        if not dry_run:
            ocm = ocm_map.get(cluster)
            ocm.del_user_from_aws_infrastructure_access_role_grants(
                cluster, user_arn, access_level
            )
    to_add = [d for d in desired_state if d not in current_state + current_deleting]
    for item in to_add:
        cluster = item["cluster"]
        user_arn = item["user_arn"]
        access_level = item["access_level"]
        logging.info(
            [
                "add_user_to_aws_infrastructure_access_role_grants",
                cluster,
                user_arn,
                access_level,
            ]
        )
        if not dry_run:
            ocm = ocm_map.get(cluster)
            ocm.add_user_to_aws_infrastructure_access_role_grants(
                cluster, user_arn, access_level
            )


def run(dry_run):
    ocm_map, current_state, current_failed, current_deleting = fetch_current_state()
    desired_state = fetch_desired_state()
    act(
        dry_run, ocm_map, current_state, current_failed, desired_state, current_deleting
    )
