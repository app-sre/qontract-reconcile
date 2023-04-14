import json
import logging
import sys
from collections.abc import (
    Callable,
    Generator,
    Mapping,
)
from typing import (
    Any,
    Optional,
)

from reconcile import queries
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.defer import defer
from reconcile.utils.ocm import (
    OCM,
    OCMMap,
)
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.terraform_client import TerraformClient as Terraform
from reconcile.utils.terrascript_aws_client import TerrascriptClient as Terrascript

QONTRACT_INTEGRATION = "terraform_tgw_attachments"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)

TGW_CONNECTION_PROVIDER = "account-tgw"


def build_desired_state_tgw_attachments(
    clusters: list[dict],
    ocm_map: OCMMap,
    awsapi: AWSApi,
) -> tuple[list[dict], bool]:
    """
    Fetch state for TGW attachments between a cluster and all TGWs
    in an account in the same region as the cluster
    """
    desired_state = []
    error = False

    for item in _build_desired_state_tgw_attachments(clusters, ocm_map, awsapi):
        if item is None:
            error = True
        else:
            desired_state.append(item)
    return desired_state, error


def _build_desired_state_tgw_attachments(
    clusters: list[dict],
    ocm_map: OCMMap,
    awsapi: AWSApi,
) -> Generator[Optional[dict], Any, None]:
    for cluster_info in clusters:
        ocm = ocm_map.get(cluster_info["name"])
        for peer_connection in cluster_info["peering"]["connections"]:
            if peer_connection["provider"] == TGW_CONNECTION_PROVIDER:
                yield from _build_desired_state_tgw_connection(
                    peer_connection, cluster_info, ocm, awsapi
                )


def _build_desired_state_tgw_connection(
    peer_connection: dict,
    cluster_info: dict,
    ocm: OCM,
    awsapi: AWSApi,
) -> Generator[Optional[dict], Any, None]:
    cluster_name = cluster_info["name"]
    cluster_region = cluster_info["spec"]["region"]
    cluster_cidr_block = cluster_info["network"]["vpc"]

    account = _account_with_assume_role_data(
        peer_connection, cluster_name, cluster_region, cluster_cidr_block, ocm
    )

    # accepter is the cluster's AWS account
    accepter = _build_accepter(
        peer_connection,
        account,
        cluster_region,
        cluster_cidr_block,
        awsapi,
    )
    if accepter["vpc_id"] is None:
        logging.error(f"[{cluster_name}] could not find VPC ID for cluster")
        yield None

    account_tgws = awsapi.get_tgws_details(
        account,
        cluster_region,
        cluster_cidr_block,
        tags=json.loads(peer_connection.get("tags") or "{}"),
        route_tables=peer_connection.get("manageRoutes"),
        security_groups=peer_connection.get("manageSecurityGroups"),
        route53_associations=peer_connection.get("manageRoute53Associations"),
    )
    for tgw in account_tgws:
        connection_name = f"{peer_connection['name']}_{account['name']}-{tgw['tgw_id']}"
        requester = _build_requester(peer_connection, account, tgw)
        item = {
            "connection_provider": TGW_CONNECTION_PROVIDER,
            "connection_name": connection_name,
            "requester": requester,
            "accepter": accepter,
            "deleted": peer_connection.get("delete", False),
        }
        yield item


def _account_with_assume_role_data(
    peer_connection: dict,
    cluster_name: str,
    region: str,
    cidr_block: str,
    ocm: OCM,
) -> dict[str, Any]:
    account = peer_connection["account"]
    # assume_role is the role to assume to provision the
    # peering connection request, through the accepter AWS account.
    provided_assume_role = peer_connection.get("assumeRole")
    # if an assume_role is provided, it means we don't need
    # to get the information from OCM. it likely means that
    # there is no OCM at all.
    account["assume_role"] = (
        provided_assume_role
        if provided_assume_role
        else ocm.get_aws_infrastructure_access_terraform_assume_role(
            cluster_name, account["uid"], account["terraformUsername"]
        )
    )
    account["assume_region"] = region
    account["assume_cidr"] = cidr_block
    return account


def _build_accepter(
    peer_connection: dict,
    account: dict,
    region: str,
    cidr_block: str,
    awsapi: AWSApi,
) -> dict:
    (vpc_id, route_table_ids, subnets_id_az) = awsapi.get_cluster_vpc_details(
        account,
        route_tables=peer_connection.get("manageRoutes"),
        subnets=True,
    )
    return {
        "cidr_block": cidr_block,
        "region": region,
        "vpc_id": vpc_id,
        "route_table_ids": route_table_ids,
        "subnets_id_az": subnets_id_az,
        "account": account,
    }


def _build_requester(
    peer_connection: dict,
    account: dict,
    tgw: dict,
) -> dict:
    return {
        "tgw_id": tgw["tgw_id"],
        "tgw_arn": tgw["tgw_arn"],
        "region": tgw["region"],
        "routes": tgw.get("routes"),
        "rules": tgw.get("rules"),
        "hostedzones": tgw.get("hostedzones"),
        "cidr_block": peer_connection.get("cidrBlock"),
        "account": account,
    }


def _build_ocm_map(
    clusters: list,
    settings: Optional[Mapping[str, Any]],
):
    with_ocm = any(c.get("ocm") for c in clusters)
    return (
        OCMMap(clusters=clusters, integration=QONTRACT_INTEGRATION, settings=settings)
        if with_ocm
        # this is a case for an OCP cluster which is not provisioned
        # through OCM. it is expected that an 'assume_role' is provided
        # on the tgw definition in the cluster file.
        else {}
    )


def _validate_vpc_connection_names(desired_state: list) -> None:
    connection_names = [c["connection_name"] for c in desired_state]
    if len(set(connection_names)) != len(connection_names):
        logging.error("duplicate vpc connection names found")
        sys.exit(1)


def _filter_accounts(accounts: list, participating_accounts: list) -> list:
    participating_account_names = {a["name"] for a in participating_accounts}
    return [a for a in accounts if a["name"] in participating_account_names]


def _populate_tgw_attachments_working_dirs(
    desired_state: list,
    accounts: list,
    settings: Optional[Mapping[str, Any]],
    participating_accounts: list,
    print_to_file: Optional[str],
    thread_pool_size: int,
) -> dict[str, str]:
    ts = Terrascript(
        QONTRACT_INTEGRATION, "", thread_pool_size, accounts, settings=settings
    )
    ts.populate_additional_providers(participating_accounts)
    ts.populate_tgw_attachments(desired_state)
    working_dirs = ts.dump(print_to_file=print_to_file)

    if print_to_file:
        sys.exit()

    return working_dirs


@defer
def run(
    dry_run: bool,
    print_to_file: Optional[str] = None,
    enable_deletion: bool = False,
    thread_pool_size: int = 10,
    defer: Optional[Callable] = None,
):
    settings = queries.get_secret_reader_settings()
    clusters = queries.get_clusters_with_peering_settings()
    ocm_map = _build_ocm_map(clusters, settings)
    accounts = queries.get_aws_accounts(terraform_state=True, ecrs=False)

    # Fetch desired state for cluster-to-vpc(account) VPCs
    with AWSApi(1, accounts, settings=settings, init_users=False) as awsapi:
        desired_state, err = build_desired_state_tgw_attachments(
            clusters, ocm_map, awsapi
        )
    if err:
        sys.exit(1)

    # check there are no repeated vpc connection names
    _validate_vpc_connection_names(desired_state)

    participating_accounts = [item["requester"]["account"] for item in desired_state]
    filtered_accounts = _filter_accounts(accounts, participating_accounts)

    working_dirs = _populate_tgw_attachments_working_dirs(
        desired_state,
        filtered_accounts,
        settings,
        participating_accounts,
        print_to_file,
        thread_pool_size,
    )

    aws_api = AWSApi(1, filtered_accounts, settings=settings, init_users=False)

    tf = Terraform(
        QONTRACT_INTEGRATION,
        QONTRACT_INTEGRATION_VERSION,
        "",
        filtered_accounts,
        working_dirs,
        thread_pool_size,
        aws_api,
    )

    if tf is None:
        sys.exit(1)

    if defer:
        defer(tf.cleanup)

    disabled_deletions_detected, err = tf.plan(enable_deletion)
    if err:
        sys.exit(1)
    if disabled_deletions_detected:
        sys.exit(1)

    if dry_run:
        return

    err = tf.apply()
    if err:
        sys.exit(1)


def early_exit_desired_state(
    print_to_file=None, enable_deletion=False, thread_pool_size=10
) -> dict[str, Any]:
    return {
        "clusters": queries.get_clusters_with_peering_settings(),
        "accounts": queries.get_aws_accounts(terraform_state=True, ecrs=False),
    }
