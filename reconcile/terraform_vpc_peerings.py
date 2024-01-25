import json
import logging
import sys
from typing import (
    Any,
    Optional,
)

import reconcile.utils.terraform_client as terraform
import reconcile.utils.terrascript_aws_client as terrascript
from reconcile import queries
from reconcile.utils import (
    aws_api,
    ocm,
)
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.defer import defer
from reconcile.utils.ocm import (
    OCM,
    OCMMap,
)
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "terraform_vpc_peerings"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class BadTerraformPeeringState(Exception):
    pass


def find_matching_peering(from_cluster, to_cluster, desired_provider):
    """
    Ensures there is a matching peering with the desired provider type
    going from the destination (to) cluster back to this one (from)
    """
    peering_info = to_cluster["peering"]
    peer_connections = peering_info["connections"]
    for peer_connection in peer_connections:
        if not peer_connection["provider"] == desired_provider:
            continue
        if not peer_connection["cluster"]:
            continue
        if from_cluster["name"] == peer_connection["cluster"]["name"]:
            return peer_connection
    return None


def _get_default_management_account(
    cluster: dict[str, Any],
) -> Optional[dict[str, Any]]:
    cluster_infra_accounts = cluster["awsInfrastructureManagementAccounts"]
    for infra_account_def in cluster_infra_accounts or []:
        if (
            infra_account_def["accessLevel"] == "network-mgmt"
            and infra_account_def.get("default") is True
        ):
            return infra_account_def["account"]
    return None


def _build_infrastructure_assume_role(
    account: dict[str, Any],
    cluster: dict[str, Any],
    ocm: Optional[OCM],
    provided_assume_role: Optional[str],
) -> Optional[dict[str, Any]]:
    if provided_assume_role:
        assume_role = provided_assume_role
    elif cluster["spec"].get("account"):
        cluster_account = cluster["spec"].get("account")
        return {
            "name": cluster_account["name"],
            "uid": cluster_account["uid"],
            "terraformUsername": cluster_account["terraformUsername"],
            "automationToken": cluster_account["automationToken"],
            "assume_region": cluster["spec"]["region"],
            "assume_cidr": cluster["network"]["vpc"],
        }
    elif ocm is not None:
        assume_role = ocm.get_aws_infrastructure_access_terraform_assume_role(
            cluster["name"],
            account["uid"],
            account["terraformUsername"],
        )
    if assume_role:
        return {
            "name": account["name"],
            "uid": account["uid"],
            "terraformUsername": account["terraformUsername"],
            "automationToken": account["automationToken"],
            "assume_role": assume_role,
            "assume_region": cluster["spec"]["region"],
            "assume_cidr": cluster["network"]["vpc"],
        }
    return None


def aws_assume_roles_for_cluster_vpc_peering(
    requester_connection: dict[str, Any],
    requester_cluster: dict[str, Any],
    accepter_connection: dict[str, Any],
    accepter_cluster: dict[str, Any],
    ocm: Optional[OCM],
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    # check if dedicated infra accounts have been declared on the
    # accepters peering connection or on the accepters cluster
    allowed_accounts = {
        a["account"]["name"]
        for a in accepter_cluster["awsInfrastructureManagementAccounts"] or []
        if a["accessLevel"] == "network-mgmt"
    }

    # check if a dedicated infra accounts have been declared on the
    # accepters peering connection
    infra_account = accepter_connection["awsInfrastructureManagementAccount"]
    if infra_account and infra_account["name"] not in allowed_accounts:
        raise BadTerraformPeeringState(
            "[account_not_allowed] "
            f"account {infra_account['name']} used on the peering accepter of "
            f"cluster {accepter_cluster['name']} is not listed as a "
            "network-mgmt in awsInfrastructureManagementAccounts"
        )

    if not infra_account:
        # look for a network-mgmt account marked as default on the accepters
        # clusters awsInfrastructureManagementAccounts
        infra_account = _get_default_management_account(accepter_cluster)

    if not infra_account:
        raise BadTerraformPeeringState(
            f"[no_account_available] unable to find infra account "
            f"for {accepter_cluster['name']} to manage the VPC peering "
            f"with {requester_cluster['name']}"
        )

    # a dedicated infra account was found on the accepter side
    # let's use it for both legs
    req_aws = _build_infrastructure_assume_role(
        infra_account, requester_cluster, ocm, requester_connection.get("assumeRole")
    )
    if req_aws is None:
        raise BadTerraformPeeringState(
            f"[assume_role_not_found] unable to find assume role "
            f"on cluster-vpc-requester for account {infra_account['name']} and "
            f"cluster {requester_cluster['name']} "
        )
    acc_aws = _build_infrastructure_assume_role(
        infra_account, accepter_cluster, ocm, accepter_connection.get("assumeRole")
    )
    if acc_aws is None:
        raise BadTerraformPeeringState(
            f"[assume_role_not_found] unable to find assume role "
            f"on cluster-vpc-accepter for account {infra_account['name']} and "
            f"cluster {accepter_cluster['name']} "
        )

    return infra_account["name"], req_aws, acc_aws


def build_desired_state_single_cluster(
    cluster_info, ocm: Optional[OCM], awsapi: AWSApi, account_filter: Optional[str]
):
    cluster_name = cluster_info["name"]

    peerings = []

    peering_info = cluster_info["peering"]
    peer_connections = peering_info["connections"]
    for peer_connection in peer_connections:
        # We only care about cluster-vpc-requester peering providers
        peer_connection_provider = peer_connection["provider"]
        if peer_connection_provider != "cluster-vpc-requester":
            continue

        peer_connection_name = peer_connection["name"]
        peer_cluster = peer_connection["cluster"]
        peer_cluster_name = peer_cluster["name"]
        requester_manage_routes = peer_connection.get("manageRoutes")
        # Ensure we have a matching peering connection
        peer_info = find_matching_peering(
            cluster_info, peer_cluster, "cluster-vpc-accepter"
        )
        if not peer_info:
            raise BadTerraformPeeringState(
                "[no_matching_peering] could not find a matching peering "
                f"connection for cluster {cluster_name}, connection "
                f"{peer_connection_name}"
            )

        accepter_manage_routes = peer_info.get("manageRoutes")

        infra_account_name, req_aws, acc_aws = aws_assume_roles_for_cluster_vpc_peering(
            peer_connection, cluster_info, peer_info, peer_cluster, ocm
        )

        # filter on account
        if (
            account_filter
            and acc_aws["name"] != account_filter
            and infra_account_name != account_filter
        ):
            continue

        requester_vpc_id, requester_route_table_ids, _, api_security_group_id = (
            awsapi.get_cluster_vpc_details(
                req_aws,
                route_tables=requester_manage_routes,
                hcp_vpc_endpoint_sg=_private_hosted_control_plane(cluster_info),
            )
        )
        if requester_vpc_id is None:
            logging.warning(
                f"[{cluster_name}] could not find VPC ID for cluster. "
                f"Skipping {peer_connection_provider} connection {peer_connection['name']}"
            )
            continue

        requester = {
            "cidr_block": cluster_info["network"]["vpc"],
            "region": cluster_info["spec"]["region"],
            "vpc_id": requester_vpc_id,
            "route_table_ids": requester_route_table_ids,
            "account": req_aws,
            "api_security_group_id": api_security_group_id,
        }

        (
            accepter_vpc_id,
            accepter_route_table_ids,
            _,
            api_security_group_id,
        ) = awsapi.get_cluster_vpc_details(
            acc_aws,
            route_tables=accepter_manage_routes,
            hcp_vpc_endpoint_sg=_private_hosted_control_plane(peer_cluster),
        )
        if accepter_vpc_id is None:
            logging.warning(
                f"[{peer_cluster_name}] could not find VPC ID for cluster. "
                f"Skipping {peer_info['provider']} connection {peer_info['name']}"
            )
            continue

        requester["peer_owner_id"] = acc_aws["uid"]
        if acc_aws.get("assume_role"):
            requester["peer_owner_id"] = acc_aws["assume_role"].split(":")[4]
        accepter = {
            "cidr_block": peer_cluster["network"]["vpc"],
            "region": peer_cluster["spec"]["region"],
            "vpc_id": accepter_vpc_id,
            "route_table_ids": accepter_route_table_ids,
            "account": acc_aws,
            "api_security_group_id": api_security_group_id,
        }

        item = {
            "connection_provider": peer_connection_provider,
            "connection_name": peer_connection_name,
            "infra_account_name": infra_account_name,
            "requester": requester,
            "accepter": accepter,
            "deleted": peer_connection.get("delete", False),
        }
        peerings.append(item)

    return peerings


def build_desired_state_all_clusters(
    clusters, ocm_map: Optional[OCMMap], awsapi: AWSApi, account_filter: Optional[str]
):
    """
    Fetch state for VPC peerings between two OCM clusters
    """
    desired_state = []
    error = False

    for cluster_info in clusters:
        try:
            cluster = cluster_info["name"]
            ocm = None if ocm_map is None else ocm_map.get(cluster)
            items = build_desired_state_single_cluster(
                cluster_info, ocm, awsapi, account_filter
            )
            desired_state.extend(items)
        except (KeyError, BadTerraformPeeringState, aws_api.MissingARNError):
            logging.exception(f"Failed to get desired state for {cluster}")
            error = True

    return desired_state, error


def build_desired_state_vpc_mesh_single_cluster(
    cluster_info, ocm: Optional[OCM], awsapi: AWSApi, account_filter: Optional[str]
):
    desired_state = []

    cluster = cluster_info["name"]
    peering_info = cluster_info["peering"]
    peer_connections = peering_info["connections"]
    for peer_connection in peer_connections:
        # We only care about account-vpc-mesh peering providers
        peer_connection_provider = peer_connection["provider"]
        if not peer_connection_provider == "account-vpc-mesh":
            continue
        # filter on account
        account = peer_connection["account"]
        if account_filter and account["name"] != account_filter:
            # not part of the shard
            continue
        # requester is the cluster's AWS account
        requester = {
            "cidr_block": cluster_info["network"]["vpc"],
            "region": cluster_info["spec"]["region"],
        }

        cluster_account = account
        # assume_role is the role to assume to provision the peering
        # connection request, through the accepter AWS account.
        provided_assume_role = peer_connection.get("assumeRole")
        if provided_assume_role:
            cluster_account["assume_role"] = provided_assume_role
        elif cluster_info["spec"].get("account"):
            cluster_account = cluster_info["spec"].get("account")
        elif ocm is not None:
            cluster_account["assume_role"] = (
                ocm.get_aws_infrastructure_access_terraform_assume_role(
                    cluster, account["uid"], account["terraformUsername"]
                )
            )
        account["assume_region"] = requester["region"]
        cluster_account["assume_region"] = requester["region"]
        cluster_account["assume_cidr"] = requester["cidr_block"]
        (
            requester_vpc_id,
            requester_route_table_ids,
            _,
            api_security_group_id,
        ) = awsapi.get_cluster_vpc_details(
            cluster_account,
            route_tables=peer_connection.get("manageRoutes"),
            hcp_vpc_endpoint_sg=_private_hosted_control_plane(cluster_info),
        )

        if requester_vpc_id is None:
            logging.warning(
                f"[{cluster}] could not find VPC ID for cluster and peer account {account}. "
                f"Skipping {peer_connection_provider} connection {peer_connection['name']}"
            )
            continue

        requester["vpc_id"] = requester_vpc_id
        requester["route_table_ids"] = requester_route_table_ids
        requester["account"] = cluster_account
        requester["api_security_group_id"] = api_security_group_id

        account_vpcs = awsapi.get_vpcs_details(
            account,
            tags=json.loads(peer_connection.get("tags") or "{}"),
            route_tables=peer_connection.get("manageRoutes"),
        )
        for vpc in account_vpcs:
            vpc_id = vpc["vpc_id"]
            connection_name = (
                f"{peer_connection['name']}_" + f"{account['name']}-{vpc_id}"
            )
            accepter = {
                "vpc_id": vpc_id,
                "region": vpc["region"],
                "cidr_block": vpc["cidr_block"],
                "route_table_ids": vpc["route_table_ids"],
                "account": account,
            }
            item = {
                "connection_provider": peer_connection_provider,
                "connection_name": connection_name,
                "infra_account_name": account["name"],
                "requester": requester,
                "accepter": accepter,
                "deleted": peer_connection.get("delete", False),
            }
            desired_state.append(item)

    return desired_state


def build_desired_state_vpc_mesh(
    clusters, ocm_map: Optional[OCMMap], awsapi: AWSApi, account_filter: Optional[str]
):
    """
    Fetch state for VPC peerings between a cluster and all VPCs in an account
    """
    desired_state = []
    error = False

    for cluster_info in clusters:
        try:
            cluster = cluster_info["name"]
            ocm = None if ocm_map is None else ocm_map.get(cluster)
            items = build_desired_state_vpc_mesh_single_cluster(
                cluster_info, ocm, awsapi, account_filter
            )
            desired_state.extend(items)
        except (KeyError, BadTerraformPeeringState, aws_api.MissingARNError):
            logging.exception(f"Unable to create VPC mesh for cluster {cluster}")
            error = True

    return desired_state, error


def build_desired_state_vpc_single_cluster(
    cluster_info, ocm: Optional[OCM], awsapi: AWSApi, account_filter: Optional[str]
):
    desired_state = []

    peering_info = cluster_info["peering"]
    peer_connections = peering_info["connections"]
    cluster = cluster_info["name"]

    for peer_connection in peer_connections:
        # We only care about account-vpc peering providers
        peer_connection_provider = peer_connection["provider"]
        if not peer_connection_provider == "account-vpc":
            continue
        # requester is the cluster's AWS account
        requester = {
            "cidr_block": cluster_info["network"]["vpc"],
            "region": cluster_info["spec"]["region"],
        }
        connection_name = peer_connection["name"]
        peer_vpc = peer_connection["vpc"]
        account = peer_vpc["account"]
        # filter on account
        if account_filter and account["name"] != account_filter:
            continue

        # accepter is the peered AWS account
        accepter = {
            "vpc_id": peer_vpc["vpc_id"],
            "cidr_block": peer_vpc["cidr_block"],
            "region": peer_vpc["region"],
        }
        if peer_connection.get("manageAccountRoutes"):
            accepter["route_table_ids"] = awsapi.get_vpc_route_table_ids(
                account, peer_vpc["vpc_id"], peer_vpc["region"]
            )

        cluster_account = account
        # assume_role is the role to assume to provision the peering
        # connection request, through the accepter AWS account.
        provided_assume_role = peer_connection.get("assumeRole")
        # if an assume_role is provided, it means we don't need
        # to get the information from OCM. it likely means that
        # there is no OCM at all.
        if provided_assume_role:
            cluster_account["assume_role"] = provided_assume_role
        elif cluster_info["spec"].get("account"):
            cluster_account = cluster_info["spec"].get("account")
        elif ocm is not None:
            cluster_account["assume_role"] = (
                ocm.get_aws_infrastructure_access_terraform_assume_role(
                    cluster,
                    peer_vpc["account"]["uid"],
                    peer_vpc["account"]["terraformUsername"],
                )
            )
        else:
            raise KeyError(
                f"[{cluster}] peering connection "
                f"{connection_name} must either specify assumeRole "
                "or ocm should be defined to obtain role to assume"
            )
        account["assume_region"] = requester["region"]
        cluster_account["assume_region"] = requester["region"]
        cluster_account["assume_cidr"] = requester["cidr_block"]
        requester_vpc_id, requester_route_table_ids, _, api_security_group_id = (
            awsapi.get_cluster_vpc_details(
                cluster_account,
                route_tables=peer_connection.get("manageRoutes"),
                hcp_vpc_endpoint_sg=_private_hosted_control_plane(cluster_info),
            )
        )

        if requester_vpc_id is None:
            logging.warning(
                f"[{cluster}] could not find VPC ID for cluster. "
                f"Skipping {peer_connection_provider} connection {peer_connection['name']}"
            )
            continue

        requester["vpc_id"] = requester_vpc_id
        requester["route_table_ids"] = requester_route_table_ids
        requester["account"] = cluster_account
        requester["api_security_group_id"] = api_security_group_id
        accepter["account"] = account
        item = {
            "connection_provider": peer_connection_provider,
            "connection_name": connection_name,
            "infra_account_name": account["name"],
            "requester": requester,
            "accepter": accepter,
            "deleted": peer_connection.get("delete", False),
        }
        desired_state.append(item)
    return desired_state


def _private_hosted_control_plane(cluster_info: dict[str, Any]) -> bool:
    return bool(
        cluster_info["spec"].get("hypershift") and cluster_info["spec"].get("private")
    )


def build_desired_state_vpc(
    clusters, ocm_map: Optional[OCMMap], awsapi: AWSApi, account_filter: Optional[str]
):
    """
    Fetch state for VPC peerings between a cluster and a VPC (account)
    """
    desired_state = []
    error = False

    for cluster_info in clusters:
        try:
            cluster = cluster_info["name"]
            ocm = None if ocm_map is None else ocm_map.get(cluster)
            items = build_desired_state_vpc_single_cluster(
                cluster_info, ocm, awsapi, account_filter
            )
            desired_state.extend(items)
        except (KeyError, BadTerraformPeeringState, aws_api.MissingARNError):
            logging.exception(f"Unable to process {cluster_info['name']}")
            error = True

    return desired_state, error


@defer
def run(
    dry_run,
    print_to_file=None,
    enable_deletion=False,
    thread_pool_size=10,
    account_name: Optional[str] = None,
    defer=None,
):
    settings = queries.get_secret_reader_settings()
    clusters = queries.get_clusters_with_peering_settings()
    with_ocm = any(c.get("ocm") for c in clusters)
    if with_ocm:
        ocm_map = ocm.OCMMap(
            clusters=clusters, integration=QONTRACT_INTEGRATION, settings=settings
        )
    else:
        # this is a case for an OCP cluster which is not provisioned
        # through OCM. it is expected that an 'assume_role' is provided
        # on the vpc peering defition in the cluster file.
        ocm_map = None

    accounts = queries.get_aws_accounts(terraform_state=True, ecrs=False)
    awsapi = aws_api.AWSApi(1, accounts, settings=settings, init_users=False)

    desired_state = []
    errors = []
    # Fetch desired state for cluster-to-vpc(account) VPCs
    desired_state_vpc, err = build_desired_state_vpc(
        clusters, ocm_map, awsapi, account_name
    )
    desired_state.extend(desired_state_vpc)
    errors.append(err)

    # Fetch desired state for cluster-to-account (vpc mesh) VPCs
    desired_state_vpc_mesh, err = build_desired_state_vpc_mesh(
        clusters, ocm_map, awsapi, account_name
    )
    desired_state.extend(desired_state_vpc_mesh)
    errors.append(err)

    # Fetch desired state for cluster-to-cluster VPCs
    desired_state_cluster, err = build_desired_state_all_clusters(
        clusters, ocm_map, awsapi, account_name
    )
    desired_state.extend(desired_state_cluster)
    errors.append(err)

    # check there are no repeated vpc connection names
    connection_names = [c["connection_name"] for c in desired_state]
    if len(set(connection_names)) != len(connection_names):
        logging.error("duplicate vpc connection names found")
        sys.exit(1)

    # infra accounts are the accounts hosting the terraform state
    # - for cluster to vpc or vpc-mesh peering, the infra account is the accepter (non-cluster) account
    # - for cluster-to-cluster peerings, the infra account is the default awsInfrastructureManagementAccount from the accepter cluster
    infra_account_names = {d["infra_account_name"] for d in desired_state}
    infra_accounts = [a for a in accounts if a["name"] in infra_account_names]
    if not infra_accounts:
        logging.warning(
            f"No participating AWS accounts found, consider disabling this integration, account name: {account_name}"
        )
        return

    participating_accounts: dict[str, list[Any]] = {}
    for infra_account_name in infra_account_names:
        participating_accounts[infra_account_name] = []
        participating_accounts[infra_account_name].extend([
            item["requester"]["account"]
            for item in desired_state
            if item["infra_account_name"] == infra_account_name
            and (
                item["requester"]["account"]["name"] != infra_account_name
                or item["requester"]["account"].get("assume_role")
            )
        ])
        participating_accounts[infra_account_name].extend([
            item["accepter"]["account"]
            for item in desired_state
            if item["infra_account_name"] == infra_account_name
            and (
                item["accepter"]["account"]["name"] != infra_account_name
                or item["accepter"]["account"].get("assume_role")
            )
        ])

    account_by_name = {a["name"]: a for a in accounts}
    with terrascript.TerrascriptClient(
        QONTRACT_INTEGRATION, "", thread_pool_size, infra_accounts, settings=settings
    ) as ts:
        rosa_cluster_accounts = [
            account_by_name[c["spec"]["account"]["name"]]
            for c in clusters
            if c.get("spec") and c["spec"].get("account")
        ]
        ts.populate_configs(rosa_cluster_accounts)

        for infra_account_name, items in participating_accounts.items():
            ts.populate_additional_providers(infra_account_name, items)
        ts.populate_vpc_peerings(desired_state)
        working_dirs = ts.dump(print_to_file=print_to_file)

    if print_to_file:
        sys.exit(0 if dry_run else int(any(errors)))

    tf = terraform.TerraformClient(
        QONTRACT_INTEGRATION,
        QONTRACT_INTEGRATION_VERSION,
        "",
        infra_accounts,
        working_dirs,
        thread_pool_size,
        awsapi,
    )

    if any(errors):
        sys.exit(1)

    defer(tf.cleanup)

    disabled_deletions_detected, err = tf.plan(enable_deletion)
    errors.append(err)
    if disabled_deletions_detected:
        logging.error("Deletions detected when they are disabled")
        sys.exit(1)

    if dry_run:
        sys.exit(int(any(errors)))
    if any(errors):
        sys.exit(1)

    errors.append(tf.apply())
    sys.exit(int(any(errors)))


def early_exit_desired_state(
    print_to_file=None,
    enable_deletion=False,
    thread_pool_size=10,
    account_name: Optional[str] = None,
) -> dict[str, Any]:
    if account_name:
        raise ValueError(
            "terraform-vpc-peerings early-exit check does not support sharding yet"
        )
    return {
        "clusters": queries.get_clusters_with_peering_settings(),
        "accounts": queries.get_aws_accounts(terraform_state=True, ecrs=False),
    }
