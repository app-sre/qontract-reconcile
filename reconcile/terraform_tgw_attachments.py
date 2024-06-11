import logging
from collections.abc import (
    Callable,
    Generator,
    Iterable,
    Mapping,
)
from typing import (
    Any,
    TypedDict,
    cast,
)

from pydantic import BaseModel

from reconcile.gql_definitions.common.app_interface_vault_settings import (
    AppInterfaceSettingsV1,
)
from reconcile.gql_definitions.common.clusters_with_peering import (
    ClusterPeeringConnectionAccountTGWV1,
    ClusterPeeringConnectionAccountV1,
    ClusterPeeringConnectionAccountVPCMeshV1,
    ClusterPeeringConnectionClusterRequesterV1,
    ClusterPeeringConnectionV1,
    ClusterSpecROSAV1,
    ClusterV1,
)
from reconcile.gql_definitions.terraform_tgw_attachments.aws_accounts import (
    AWSAccountV1,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.clusters_with_peering import get_clusters_with_peering
from reconcile.typed_queries.terraform_tgw_attachments.aws_accounts import (
    get_aws_accounts,
)
from reconcile.utils import gql
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.defer import defer
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.extended_early_exit import (
    ExtendedEarlyExitRunnerResult,
    extended_early_exit_run,
)
from reconcile.utils.ocm import (
    OCM,
    OCMMap,
)
from reconcile.utils.runtime.integration import DesiredStateShardConfig
from reconcile.utils.secret_reader import SecretReaderBase, create_secret_reader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.terraform_client import TerraformClient as Terraform
from reconcile.utils.terrascript_aws_client import TerrascriptClient as Terrascript
from reconcile.utils.unleash import get_feature_toggle_state

QONTRACT_INTEGRATION = "terraform_tgw_attachments"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)

TGW_CONNECTION_PROVIDER = "account-tgw"


class ValidationError(Exception):
    pass


class AccountProviderInfo(BaseModel):
    name: str
    uid: str
    assume_role: str | None
    assume_region: str
    assume_cidr: str


class Requester(BaseModel):
    tgw_id: str
    tgw_arn: str
    region: str
    routes: list[dict] | None
    rules: list[dict] | None
    hostedzones: list[str] | None
    cidr_block: str
    account: AccountProviderInfo


class Accepter(BaseModel):
    cidr_block: str
    region: str
    vpc_id: str | None
    route_table_ids: list[str] | None
    subnets_id_az: list[dict] | None
    account: AccountProviderInfo
    api_security_group_id: str | None


class DesiredStateItem(BaseModel):
    connection_provider: str
    connection_name: str
    infra_acount_name: str
    requester: Requester
    accepter: Accepter
    deleted: bool


class DesiredStateDataSource(BaseModel):
    clusters: list[ClusterV1]
    accounts: list[AWSAccountV1]


class CacheSource(TypedDict):
    terraform_configurations: dict[str, str]


class RunnerParams(TypedDict):
    terraform_client: Terraform
    terrascript_client: Terrascript
    dry_run: bool
    enable_deletion: bool


def _build_desired_state_tgw_attachments(
    clusters: Iterable[ClusterV1],
    ocm_map: OCMMap | None,
    awsapi: AWSApi,
    account_name: str | None = None,
) -> tuple[list[DesiredStateItem], bool]:
    """
    Fetch state for TGW attachments between a cluster and all TGWs
    in an account in the same region as the cluster
    """
    desired_state = []
    error = False

    for item in _build_desired_state_items(clusters, ocm_map, awsapi, account_name):
        if item is None:
            error = True
        else:
            desired_state.append(item)
    return desired_state, error


def _build_desired_state_items(
    clusters: Iterable[ClusterV1],
    ocm_map: OCMMap | None,
    awsapi: AWSApi,
    account_name: str | None = None,
) -> Generator[DesiredStateItem | None, Any, None]:
    for cluster_info in clusters:
        ocm = ocm_map.get(cluster_info.name) if ocm_map and cluster_info.ocm else None
        for peer_connection in cluster_info.peering.connections:  # type: ignore[union-attr]
            if _is_tgw_peer_connection(peer_connection, account_name):
                yield from _build_desired_state_tgw_connection(
                    cast(ClusterPeeringConnectionAccountTGWV1, peer_connection),
                    cluster_info,
                    ocm,
                    awsapi,
                )


def _build_desired_state_tgw_connection(
    peer_connection: ClusterPeeringConnectionAccountTGWV1,
    cluster_info: ClusterV1,
    ocm: OCM | None,
    awsapi: AWSApi,
) -> Generator[DesiredStateItem | None, Any, None]:
    cluster_name = cluster_info.name
    cluster_region = cluster_info.spec.region if cluster_info.spec is not None else ""
    cluster_cidr_block = (
        cluster_info.network.vpc if cluster_info.network is not None else ""
    )

    acc_account = _build_account_with_assume_role(
        peer_connection, cluster_info, cluster_region, cluster_cidr_block, ocm
    )

    # accepter is the cluster's AWS account
    accepter = _build_accepter(
        peer_connection,
        acc_account,
        cluster_region,
        cluster_cidr_block,
        awsapi,
        private_hcp=_is_private_hosted_control_plane(cluster_info),
    )
    if accepter.vpc_id is None:
        logging.error(f"[{cluster_name}] could not find VPC ID for cluster")
        yield None

    account_tgws = awsapi.get_tgws_details(
        peer_connection.account.dict(by_alias=True),
        cluster_region,
        cluster_cidr_block,
        tags=peer_connection.tags or {},
        route_tables=peer_connection.manage_routes,
        security_groups=peer_connection.manage_security_groups,
        route53_associations=peer_connection.manage_route53_associations,
    )
    for tgw in account_tgws:
        connection_name = (
            f"{peer_connection.name}_{peer_connection.account.name}-{tgw['tgw_id']}"
        )
        requester = _build_requester(peer_connection, tgw)
        item = DesiredStateItem(
            connection_provider=TGW_CONNECTION_PROVIDER,
            connection_name=connection_name,
            infra_acount_name=peer_connection.account.name,
            requester=requester,
            accepter=accepter,
            deleted=peer_connection.delete or False,
        )
        yield item


def _is_private_hosted_control_plane(cluster_info: ClusterV1) -> bool:
    return (
        cluster_info.spec is not None
        and bool(cluster_info.spec.hypershift)
        and bool(cluster_info.spec.private)
    )


def _build_account_with_assume_role(
    peer_connection: ClusterPeeringConnectionAccountTGWV1,
    cluster: ClusterV1,
    region: str,
    cidr_block: str,
    ocm: OCM | None,
) -> AccountProviderInfo:
    account = peer_connection.account
    # assume_role is the role to assume to provision the
    # peering connection request, through the accepter AWS account.
    assume_role = peer_connection.assume_role
    # if an assume_role is provided, it means we don't need
    # to get the information from OCM. it likely means that
    # there is no OCM at all.
    if not assume_role:
        if isinstance(cluster.spec, ClusterSpecROSAV1) and cluster.spec.account:
            return AccountProviderInfo(
                name=cluster.spec.account.name,
                uid=cluster.spec.account.uid,
                assume_role=assume_role,
                assume_region=region,
                assume_cidr=cidr_block,
            )
        if not ocm:
            raise ValueError("OCM is required to get assume_role data")
        assume_role = ocm.get_aws_infrastructure_access_terraform_assume_role(
            cluster.name, account.uid, account.terraform_username
        )
    return AccountProviderInfo(
        name=account.name,
        uid=account.uid,
        assume_role=assume_role,
        assume_region=region,
        assume_cidr=cidr_block,
    )


def _build_accepter(
    peer_connection: ClusterPeeringConnectionAccountTGWV1,
    account: AccountProviderInfo,
    region: str,
    cidr_block: str,
    awsapi: AWSApi,
    private_hcp: bool = False,
) -> Accepter:
    allow_hcp_private_api_access = (
        private_hcp and peer_connection.allow_private_hcp_api_access
    )
    (vpc_id, route_table_ids, subnets_id_az, api_security_group_id) = (
        awsapi.get_cluster_vpc_details(
            account.dict(by_alias=True),
            route_tables=peer_connection.manage_routes,
            subnets=True,
            hcp_vpc_endpoint_sg=allow_hcp_private_api_access,
        )
    )
    return Accepter(
        cidr_block=cidr_block,
        region=region,
        vpc_id=vpc_id,
        route_table_ids=route_table_ids,
        subnets_id_az=subnets_id_az,
        account=account,
        api_security_group_id=api_security_group_id,
    )


def _build_requester(
    peer_connection: ClusterPeeringConnectionAccountTGWV1,
    tgw: Mapping,
) -> Requester:
    tgw_account = AccountProviderInfo(
        name=peer_connection.account.name,
        uid=peer_connection.account.uid,
        assume_region=tgw["region"],
        assume_cidr=peer_connection.cidr_block,
    )
    return Requester(
        tgw_id=tgw["tgw_id"],
        tgw_arn=tgw["tgw_arn"],
        region=tgw["region"],
        routes=tgw.get("routes"),
        rules=tgw.get("rules"),
        hostedzones=tgw.get("hostedzones"),
        cidr_block=peer_connection.cidr_block,
        account=tgw_account,
    )


def _build_ocm_map(
    clusters: Iterable[ClusterV1],
    vault_settings: AppInterfaceSettingsV1,
) -> OCMMap | None:
    ocm_clusters = [c.dict(by_alias=True) for c in clusters if c.ocm]
    return (
        OCMMap(
            clusters=ocm_clusters,
            integration=QONTRACT_INTEGRATION,
            settings=vault_settings.dict(by_alias=True),
        )
        if ocm_clusters
        # this is a case for an OCP cluster which is not provisioned
        # through OCM. it is expected that an 'assume_role' is provided
        # on the tgw definition in the cluster file.
        else None
    )


def _validate_tgw_connection_names(desired_state: Iterable[DesiredStateItem]) -> None:
    connection_names = [c.connection_name for c in desired_state]
    if len(set(connection_names)) != len(connection_names):
        raise ValidationError("duplicate tgw connection names found")


def _populate_tgw_attachments_working_dirs(
    ts: Terrascript,
    desired_state: Iterable[DesiredStateItem],
    print_to_file: str | None,
) -> dict[str, str]:
    accounts_by_infra_account_name: dict[str, list[dict[str, Any]]] = {}
    for item in desired_state:
        accounts_by_infra_account_name.setdefault(item.infra_acount_name, []).append(
            item.accepter.account.dict(by_alias=True)
        )
    for infra_account_name, accounts in accounts_by_infra_account_name.items():
        ts.populate_additional_providers(infra_account_name, accounts)
    ts.populate_tgw_attachments(desired_state)
    working_dirs = ts.dump(print_to_file=print_to_file)
    return working_dirs


def _is_tgw_peer_connection(
    peer_connection: ClusterPeeringConnectionAccountTGWV1
    | ClusterPeeringConnectionAccountV1
    | ClusterPeeringConnectionAccountVPCMeshV1
    | ClusterPeeringConnectionClusterRequesterV1
    | ClusterPeeringConnectionV1,
    account_name: str | None,
) -> bool:
    if peer_connection.provider != TGW_CONNECTION_PROVIDER:
        return False
    if account_name is None:
        return True
    tgw_peer_connection = cast(ClusterPeeringConnectionAccountTGWV1, peer_connection)
    return tgw_peer_connection.account.name == account_name


def _is_tgw_cluster(
    cluster: ClusterV1,
    account_name: str | None = None,
) -> bool:
    return any(
        _is_tgw_peer_connection(pc, account_name)
        for pc in cluster.peering.connections  # type: ignore[union-attr]
    )


def _filter_tgw_clusters(
    clusters: Iterable[ClusterV1],
    account_name: str | None = None,
) -> list[ClusterV1]:
    return [c for c in clusters if _is_tgw_cluster(c, account_name)]


def _filter_tgw_accounts(
    accounts: Iterable[AWSAccountV1],
    tgw_clusters: Iterable[ClusterV1],
) -> list[AWSAccountV1]:
    tgw_account_names = set()
    for cluster in tgw_clusters:
        for peer_connection in cluster.peering.connections:  # type: ignore[union-attr]
            if peer_connection.provider == TGW_CONNECTION_PROVIDER:
                tgw_peer_connection = cast(
                    ClusterPeeringConnectionAccountTGWV1, peer_connection
                )
                tgw_account_names.add(tgw_peer_connection.account.name)
    return [
        a
        for a in accounts
        if a.name in tgw_account_names
        and integration_is_enabled(QONTRACT_INTEGRATION.replace("_", "-"), a)
    ]


def _fetch_desired_state_data_source(
    account_name: str | None = None,
) -> DesiredStateDataSource:
    clusters = get_clusters_with_peering(gql.get_api())
    tgw_clusters = _filter_tgw_clusters(clusters, account_name)
    all_accounts = get_aws_accounts(gql.get_api())
    return DesiredStateDataSource(
        clusters=tgw_clusters,
        accounts=all_accounts,
    )


def setup(
    account_name: str | None,
    desired_state_data_source: DesiredStateDataSource,
    tgw_accounts: list[dict[str, Any]],
    thread_pool_size: int = 10,
    print_to_file: str | None = None,
) -> tuple[SecretReaderBase, AWSApi, Terraform, Terrascript]:
    tgw_clusters = desired_state_data_source.clusters
    all_accounts = [a.dict(by_alias=True) for a in desired_state_data_source.accounts]
    account_by_name = {a["name"]: a for a in all_accounts}
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(vault_settings.vault)
    aws_api = AWSApi(1, all_accounts, secret_reader=secret_reader, init_users=False)
    ocm_map = _build_ocm_map(desired_state_data_source.clusters, vault_settings)
    desired_state, err = _build_desired_state_tgw_attachments(
        desired_state_data_source.clusters,
        ocm_map,
        aws_api,
        account_name,
    )
    if err:
        raise RuntimeError("Could not find VPC ID for cluster")

    _validate_tgw_connection_names(desired_state)

    ts = Terrascript(
        QONTRACT_INTEGRATION,
        "",
        thread_pool_size,
        tgw_accounts,
        settings=vault_settings.dict(by_alias=True),
    )
    tgw_rosa_cluster_accounts = [
        account_by_name[c.spec.account.name]
        for c in tgw_clusters
        if isinstance(c.spec, ClusterSpecROSAV1) and c.spec.account
    ]
    ts.populate_configs(tgw_rosa_cluster_accounts)
    working_dirs = _populate_tgw_attachments_working_dirs(
        ts,
        desired_state,
        print_to_file,
    )
    tf = Terraform(
        QONTRACT_INTEGRATION,
        QONTRACT_INTEGRATION_VERSION,
        "",
        tgw_accounts,
        working_dirs,
        thread_pool_size,
        aws_api,
    )
    return secret_reader, aws_api, tf, ts


def runner(
    dry_run: bool,
    terraform_client: Terraform,
    terrascript_client: Terrascript,
    enable_deletion: bool = False,
) -> ExtendedEarlyExitRunnerResult:
    disabled_deletions_detected, err = terraform_client.plan(enable_deletion)
    if err:
        raise RuntimeError("Error running terraform plan")
    if disabled_deletions_detected:
        raise RuntimeError("Disabled deletions detected running terraform plan")
    if not dry_run:
        err = terraform_client.apply()
        if err:
            raise RuntimeError("Error running terraform apply")
    return ExtendedEarlyExitRunnerResult(
        payload=terrascript_client.terraform_configurations(),
        applied_count=terraform_client.apply_count,
    )


@defer
def run(
    dry_run: bool,
    print_to_file: str | None = None,
    enable_deletion: bool = False,
    thread_pool_size: int = 10,
    account_name: str | None = None,
    defer: Callable | None = None,
    enable_extended_early_exit: bool = False,
    extended_early_exit_cache_ttl_seconds: int = 3600,
    log_cached_log_output: bool = False,
) -> None:
    desired_state_data_source = _fetch_desired_state_data_source(account_name)
    tgw_accounts = [
        a.dict(by_alias=True)
        for a in _filter_tgw_accounts(
            desired_state_data_source.accounts, desired_state_data_source.clusters
        )
        if not account_name or account_name == a.name
    ]
    if not tgw_accounts:
        logging.warning(
            f"No participating AWS accounts found, consider disabling this integration, account name: {account_name}"
        )
        return
    secret_reader, aws_api, tf, ts = setup(
        desired_state_data_source=desired_state_data_source,
        account_name=account_name,
        tgw_accounts=tgw_accounts,
        thread_pool_size=thread_pool_size,
        print_to_file=print_to_file,
    )
    if defer:
        defer(aws_api.cleanup)
        defer(tf.cleanup)
    if print_to_file:
        return
    runner_params: RunnerParams = dict(
        terraform_client=tf,
        terrascript_client=ts,
        enable_deletion=enable_deletion,
        dry_run=dry_run,
    )
    if enable_extended_early_exit and get_feature_toggle_state(
        "terraform-tgw-attachments-extended-early-exit",
        default=False,
    ):
        cache_source = CacheSource(
            terraform_configurations=ts.terraform_configurations(),
        )
        extended_early_exit_run(
            integration=QONTRACT_INTEGRATION,
            integration_version=QONTRACT_INTEGRATION_VERSION,
            dry_run=dry_run,
            cache_source=cache_source,
            shard="_".join(account_name) if account_name else "",
            ttl_seconds=extended_early_exit_cache_ttl_seconds,
            logger=logging.getLogger(),
            runner=runner,
            runner_params=runner_params,
            secret_reader=secret_reader,
            log_cached_log_output=log_cached_log_output,
        )
    else:
        runner(**runner_params)


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    desired_state = _fetch_desired_state_data_source()
    for a in desired_state.accounts:
        a.deletion_approvals = []
    return desired_state.dict(by_alias=True)


def desired_state_shard_config() -> DesiredStateShardConfig:
    return DesiredStateShardConfig(
        shard_arg_name="account_name",
        shard_path_selectors={
            "accounts[*].name",
            "clusters[*].peering.connections[*].account.name",
        },
        sharded_run_review=lambda proposal: len(proposal.proposed_shards) <= 2,
    )
