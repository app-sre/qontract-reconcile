import json
import logging
from collections.abc import (
    Callable,
    Generator,
    Iterable,
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


class ValidationError(Exception):
    pass


def build_desired_state_tgw_attachments(
    clusters: Iterable[Mapping],
    ocm_map: Optional[OCMMap],
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
    clusters: Iterable[Mapping],
    ocm_map: Optional[OCMMap],
    awsapi: AWSApi,
) -> Generator[Optional[dict], Any, None]:
    for cluster_info in clusters:
        ocm = (
            ocm_map.get(cluster_info["name"])
            if ocm_map and cluster_info.get("ocm")
            else None
        )
        for peer_connection in cluster_info["peering"]["connections"]:
            if peer_connection["provider"] == TGW_CONNECTION_PROVIDER:
                yield from _build_desired_state_tgw_connection(
                    peer_connection, cluster_info, ocm, awsapi
                )


def _build_desired_state_tgw_connection(
    peer_connection: Mapping,
    cluster_info: Mapping,
    ocm: Optional[OCM],
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
    peer_connection: Mapping,
    cluster_name: str,
    region: str,
    cidr_block: str,
    ocm: Optional[OCM],
) -> dict[str, Any]:
    account = peer_connection["account"]
    # assume_role is the role to assume to provision the
    # peering connection request, through the accepter AWS account.
    provided_assume_role = peer_connection.get("assumeRole")
    # if an assume_role is provided, it means we don't need
    # to get the information from OCM. it likely means that
    # there is no OCM at all.
    if provided_assume_role:
        account["assume_role"] = provided_assume_role
    else:
        if not ocm:
            raise ValueError("OCM is required to get assume_role data")
        account[
            "assume_role"
        ] = ocm.get_aws_infrastructure_access_terraform_assume_role(
            cluster_name, account["uid"], account["terraformUsername"]
        )
    account["assume_region"] = region
    account["assume_cidr"] = cidr_block
    return account


def _build_accepter(
    peer_connection: Mapping,
    account: Mapping,
    region: str,
    cidr_block: str,
    awsapi: AWSApi,
) -> dict[str, Any]:
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
    peer_connection: Mapping,
    account: Mapping,
    tgw: Mapping,
) -> dict[str, Any]:
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
    clusters: Iterable[Mapping],
    settings: Optional[Mapping[str, Any]],
) -> Optional[OCMMap]:
    ocm_clusters = [c for c in clusters if c.get("ocm")]
    return (
        OCMMap(
            clusters=ocm_clusters, integration=QONTRACT_INTEGRATION, settings=settings
        )
        if ocm_clusters
        # this is a case for an OCP cluster which is not provisioned
        # through OCM. it is expected that an 'assume_role' is provided
        # on the tgw definition in the cluster file.
        else None
    )


def _validate_tgw_connection_names(desired_state: Iterable[Mapping]) -> None:
    connection_names = [c["connection_name"] for c in desired_state]
    if len(set(connection_names)) != len(connection_names):
        raise ValidationError("duplicate tgw connection names found")


def _populate_tgw_attachments_working_dirs(
    desired_state: Iterable,
    accounts: Iterable,
    settings: Optional[Mapping[str, Any]],
    participating_accounts: Iterable,
    print_to_file: Optional[str],
    thread_pool_size: int,
) -> dict[str, str]:
    ts = Terrascript(
        QONTRACT_INTEGRATION, "", thread_pool_size, accounts, settings=settings
    )
    ts.populate_additional_providers(participating_accounts)
    ts.populate_tgw_attachments(desired_state)
    working_dirs = ts.dump(print_to_file=print_to_file)
    return working_dirs


def _is_tgw_cluster(cluster: Mapping) -> bool:
    return any(
        pc["provider"] == TGW_CONNECTION_PROVIDER
        for pc in cluster["peering"]["connections"]
    )


def _filter_tgw_clusters(clusters: Iterable[Mapping]) -> list:
    return list(filter(_is_tgw_cluster, clusters))


def _filter_tgw_accounts(
    accounts: Iterable[Mapping],
    tgw_clusters: Iterable[Mapping],
) -> list:
    tgw_account_names = set()
    for cluster in tgw_clusters:
        for pc in cluster["peering"]["connections"]:
            if pc["provider"] == TGW_CONNECTION_PROVIDER:
                tgw_account_names.add(pc["account"]["name"])
    return [a for a in accounts if a["name"] in tgw_account_names]


@defer
def run(
    dry_run: bool,
    print_to_file: Optional[str] = None,
    enable_deletion: bool = False,
    thread_pool_size: int = 10,
    defer: Optional[Callable] = None,
) -> None:
    settings = queries.get_secret_reader_settings()
    clusters = queries.get_clusters_with_peering_settings()
    tgw_clusters = _filter_tgw_clusters(clusters)
    ocm_map = _build_ocm_map(tgw_clusters, settings)
    accounts = queries.get_aws_accounts(terraform_state=True, ecrs=False)
    tgw_accounts = _filter_tgw_accounts(accounts, tgw_clusters)

    aws_api = AWSApi(1, tgw_accounts, settings=settings, init_users=False)
    if defer:
        defer(aws_api.cleanup)

    # Fetch desired state for cluster-to-vpc(account) VPCs
    desired_state, err = build_desired_state_tgw_attachments(
        tgw_clusters, ocm_map, aws_api
    )
    if err:
        raise RuntimeError("Could not find VPC ID for cluster")

    # check there are no repeated tgw connection names
    _validate_tgw_connection_names(desired_state)

    participating_accounts = [item["requester"]["account"] for item in desired_state]

    working_dirs = _populate_tgw_attachments_working_dirs(
        desired_state,
        tgw_accounts,
        settings,
        participating_accounts,
        print_to_file,
        thread_pool_size,
    )

    if print_to_file:
        return

    tf = Terraform(
        QONTRACT_INTEGRATION,
        QONTRACT_INTEGRATION_VERSION,
        "",
        tgw_accounts,
        working_dirs,
        thread_pool_size,
        aws_api,
    )

    if defer:
        defer(tf.cleanup)

    disabled_deletions_detected, err = tf.plan(enable_deletion)
    if err:
        raise RuntimeError("Error running terraform plan")
    if disabled_deletions_detected:
        raise RuntimeError("Disabled deletions detected running terraform plan")

    if dry_run:
        return

    err = tf.apply()
    if err:
        raise RuntimeError("Error running terraform apply")


def early_exit_desired_state(
    print_to_file: Optional[str] = None,
    enable_deletion: bool = False,
    thread_pool_size: int = 10,
) -> dict[str, Any]:
    return {
        "clusters": queries.get_clusters_with_peering_settings(),
        "accounts": queries.get_aws_accounts(terraform_state=True, ecrs=False),
    }
