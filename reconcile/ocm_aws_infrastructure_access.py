import logging
import sys
from collections.abc import Mapping
from typing import Any

from reconcile import queries
from reconcile.status import ExitCodes
from reconcile.typed_queries.terraform_namespaces import get_namespaces
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.external_resources import (
    PROVIDER_AWS,
    get_external_resource_specs,
)
from reconcile.utils.ocm import (
    OCM_PRODUCT_OSD,
    STATUS_DELETING,
    STATUS_FAILED,
    OCMMap,
)

QONTRACT_INTEGRATION = "ocm-aws-infrastructure-access"
SUPPORTED_OCM_PRODUCTS = [OCM_PRODUCT_OSD]


def fetch_current_state(clusters):
    current_state = []
    current_failed = []
    current_deleting = []
    settings = queries.get_app_interface_settings()

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


def fetch_desired_state(clusters):
    desired_state = []

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

    # get desired state defined in external resources
    # section for aws-iam-service-account resources
    # of namespace files
    aws_accounts = queries.get_aws_accounts()
    namespaces = get_namespaces()
    for namespace_info in namespaces:
        specs = get_external_resource_specs(
            namespace_info.dict(by_alias=True), provision_provider=PROVIDER_AWS
        )
        for spec in specs:
            if spec.provider != "aws-iam-service-account":
                continue
            aws_infrastructure_access = (
                spec.resource.get("aws_infrastructure_access") or None
            )
            if aws_infrastructure_access is None:
                continue
            if aws_infrastructure_access.get("assume_role"):
                continue
            aws_account_uid = next(
                a["uid"] for a in aws_accounts if a["name"] == spec.provisioner_name
            )
            cluster = aws_infrastructure_access["cluster"]["name"]
            access_level = aws_infrastructure_access["access_level"]
            item = {
                "cluster": cluster,
                "user_arn": f"arn:aws:iam::{aws_account_uid}:user/{spec.identifier}",
                "access_level": access_level,
            }
            desired_state.append(item)

    return desired_state


def act(
    dry_run, ocm_map, current_state, current_failed, desired_state, current_deleting
):
    to_delete = [c for c in current_state if c not in desired_state]
    to_delete += current_failed
    for item in to_delete:
        cluster = item["cluster"]
        user_arn = item["user_arn"]
        access_level = item["access_level"]
        logging.info([
            "del_user_from_aws_infrastructure_access_role_grants",
            cluster,
            user_arn,
            access_level,
        ])
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
        logging.info([
            "add_user_to_aws_infrastructure_access_role_grants",
            cluster,
            user_arn,
            access_level,
        ])
        if not dry_run:
            ocm = ocm_map.get(cluster)
            ocm.add_user_to_aws_infrastructure_access_role_grants(
                cluster, user_arn, access_level
            )


def _cluster_is_compatible(cluster: Mapping[str, Any]) -> bool:
    return (
        cluster.get("ocm") is not None
        and cluster["spec"]["product"] in SUPPORTED_OCM_PRODUCTS
    )


def get_clusters():
    return [
        c
        for c in queries.get_clusters(aws_infrastructure_access=True)
        if integration_is_enabled(QONTRACT_INTEGRATION, c) and _cluster_is_compatible(c)
    ]


def run(dry_run):
    clusters = get_clusters()
    if not clusters:
        logging.debug(
            "No OCM Aws infrastructure access definitions found in app-interface"
        )
        sys.exit(ExitCodes.SUCCESS)

    ocm_map, current_state, current_failed, current_deleting = fetch_current_state(
        clusters
    )
    desired_state = fetch_desired_state(clusters)
    act(
        dry_run, ocm_map, current_state, current_failed, desired_state, current_deleting
    )


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {"state": fetch_desired_state(clusters=get_clusters())}
