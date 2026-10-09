from __future__ import annotations

import logging
import sys
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from qontract_utils.differ import diff_iterables

from reconcile import queries
from reconcile.gql_definitions.ocm_aws_infrastructure_access.clusters import (
    ClusterV1,
    UserV1,
)
from reconcile.gql_definitions.ocm_aws_infrastructure_access.clusters import (
    query as clusters_query,
)
from reconcile.status import ExitCodes
from reconcile.typed_queries.terraform_namespaces import get_namespaces
from reconcile.utils import gql
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.aws_iam_identity import require_iam_users
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.external_resources import (
    PROVIDER_AWS,
    get_external_resource_specs,
)
from reconcile.utils.membershipsources.resolver import (
    resolve_role_members,
)
from reconcile.utils.ocm import (
    OCM_PRODUCT_OSD,
    STATUS_DELETING,
    STATUS_FAILED,
    OCMMap,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from reconcile.gql_definitions.fragments.aws_account_common import AWSAccountCommon

QONTRACT_INTEGRATION = "ocm-aws-infrastructure-access"
SUPPORTED_OCM_PRODUCTS = [OCM_PRODUCT_OSD]


class InfrastructureGrant(BaseModel, frozen=True):
    """Desired or current IAM infrastructure-access grant."""

    cluster: str
    user_arn: str
    access_level: str

    @property
    def key(self) -> tuple[str, str, str]:
        """Identity used for comparing grants without changing access levels."""
        return self.cluster, self.user_arn, self.access_level


def fetch_current_state(
    clusters: Iterable[ClusterV1],
) -> tuple[
    OCMMap,
    list[InfrastructureGrant],
    list[InfrastructureGrant],
    list[InfrastructureGrant],
]:
    clusters = list(clusters)
    current_state = []
    current_failed = []
    current_deleting = []
    settings = queries.get_app_interface_settings()

    ocm_map = OCMMap(
        clusters=[cluster.model_dump(by_alias=True) for cluster in clusters],
        integration=QONTRACT_INTEGRATION,
        settings=settings,
    )

    for cluster_info in clusters:
        cluster = cluster_info.name
        ocm = ocm_map.get(cluster)
        role_grants = ocm.get_aws_infrastructure_access_role_grants(cluster)
        for user_arn, access_level, state, _ in role_grants:
            item = InfrastructureGrant(
                cluster=cluster, user_arn=user_arn, access_level=access_level
            )
            if state == STATUS_FAILED:
                current_failed.append(item)
            elif state == STATUS_DELETING:
                current_deleting.append(item)
            else:
                current_state.append(item)

    return ocm_map, current_state, current_failed, current_deleting


def fetch_desired_state(clusters: Iterable[ClusterV1]) -> list[InfrastructureGrant]:
    desired_state: list[InfrastructureGrant] = []
    clusters = list(clusters)
    required_accounts: dict[str, AWSAccountCommon] = {}
    required_users: dict[str, set[str]] = defaultdict(set)

    for cluster_info in clusters:
        cluster = cluster_info.name
        aws_infra_access_items = cluster_info.aws_infrastructure_access or []
        for aws_infra_access in aws_infra_access_items:
            aws_group = aws_infra_access.aws_group
            access_level = aws_infra_access.access_level
            aws_account = aws_group.account
            aws_account_uid = aws_account.uid
            for role in aws_group.roles or []:
                usernames = {
                    member.aws_username or member.org_username for member in role.users
                }
                if role.member_sources and usernames:
                    required_accounts[aws_account.name] = aws_account
                    required_users[aws_account.name].update(usernames)
                desired_state.extend(
                    InfrastructureGrant(
                        cluster=cluster,
                        user_arn=f"arn:aws:iam::{aws_account_uid}:user/{username}",
                        access_level=access_level,
                    )
                    for username in usernames
                )

        aws_infra_management_items = (
            cluster_info.aws_infrastructure_management_accounts or []
        )
        for aws_infra_management in aws_infra_management_items:
            management_account = aws_infra_management.account
            access_level = aws_infra_management.access_level
            aws_account_uid = management_account.uid
            # add terraform user account
            tf_user = management_account.terraform_username
            if tf_user:
                item = InfrastructureGrant(
                    cluster=cluster,
                    user_arn=f"arn:aws:iam::{aws_account_uid}:user/{tf_user}",
                    access_level=access_level,
                )
                desired_state.append(item)

    if required_accounts:
        with AWSApi(
            1,
            [
                account.model_dump(by_alias=True)
                for account in required_accounts.values()
            ],
            settings=queries.get_app_interface_settings(),
        ) as aws_api:
            for account_name, usernames in required_users.items():
                require_iam_users(
                    aws_api, account_name=account_name, usernames=usernames
                )

    # get desired state defined in external resources
    # section for aws-iam-service-account resources
    # of namespace files
    aws_accounts = queries.get_aws_accounts()
    namespaces = get_namespaces()
    for namespace_info in namespaces:
        specs = get_external_resource_specs(
            namespace_info.model_dump(by_alias=True), provision_provider=PROVIDER_AWS
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
            item = InfrastructureGrant(
                cluster=cluster,
                user_arn=f"arn:aws:iam::{aws_account_uid}:user/{spec.identifier}",
                access_level=access_level,
            )
            desired_state.append(item)

    return desired_state


def act(
    dry_run: bool,
    ocm_map: OCMMap,
    current_state: list[InfrastructureGrant],
    current_failed: Iterable[InfrastructureGrant],
    desired_state: Iterable[InfrastructureGrant],
    current_deleting: list[InfrastructureGrant],
) -> None:
    desired_state = list(desired_state)
    diff = diff_iterables(current_state, desired_state, key=lambda grant: grant.key)
    to_delete = [*diff.delete.values(), *current_failed]
    for item in to_delete:
        cluster = item.cluster
        user_arn = item.user_arn
        access_level = item.access_level
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
    to_add = diff_iterables(
        [*current_state, *current_deleting], desired_state, key=lambda grant: grant.key
    ).add.values()
    for item in to_add:
        cluster = item.cluster
        user_arn = item.user_arn
        access_level = item.access_level
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


def _cluster_is_compatible(cluster: ClusterV1) -> bool:
    return (
        cluster.ocm is not None
        and cluster.spec is not None
        and cluster.spec.product in SUPPORTED_OCM_PRODUCTS
    )


def get_clusters() -> list[ClusterV1]:
    """Fetch compatible clusters with resolved infrastructure-access roles."""
    query_func = gql.get_api().query
    clusters = [
        c.model_copy(deep=True)
        for c in clusters_query(query_func=query_func).clusters or []
        if integration_is_enabled(QONTRACT_INTEGRATION, c) and _cluster_is_compatible(c)
    ]
    resolved_roles = resolve_role_members(
        [
            role
            for cluster in clusters
            for access in cluster.aws_infrastructure_access or []
            for role in access.aws_group.roles or []
        ],
        user_cls=UserV1,
        query_func=query_func,
    )
    roles_by_name = {role.name: role for role in resolved_roles}
    for cluster in clusters:
        for access in cluster.aws_infrastructure_access or []:
            if access.aws_group.roles is not None:
                access.aws_group.roles = [
                    roles_by_name[role.name] for role in access.aws_group.roles
                ]
    return clusters


def run(dry_run: bool) -> None:
    clusters = get_clusters()
    if not clusters:
        logging.debug(
            "No OCM Aws infrastructure access definitions found in app-interface"
        )
        sys.exit(ExitCodes.SUCCESS)

    desired_state = fetch_desired_state(clusters)
    ocm_map, current_state, current_failed, current_deleting = fetch_current_state(
        clusters
    )
    act(
        dry_run, ocm_map, current_state, current_failed, desired_state, current_deleting
    )


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {
        "state": [
            grant.model_dump() for grant in fetch_desired_state(clusters=get_clusters())
        ]
    }
