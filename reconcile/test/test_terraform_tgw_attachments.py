from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from unittest.mock import create_autospec

import pytest
from pytest_mock import MockerFixture

import reconcile.terraform_tgw_attachments as integ
from reconcile.gql_definitions.common.app_interface_vault_settings import (
    AppInterfaceSettingsV1,
)
from reconcile.gql_definitions.common.clusters_with_peering import (
    ClusterPeeringConnectionAccountTGWV1,
    ClusterPeeringConnectionAccountTGWV1_AWSAccountV1,
    ClusterPeeringConnectionAccountV1,
    ClusterPeeringConnectionAccountVPCMeshV1,
    ClusterPeeringConnectionClusterRequesterV1,
    ClusterPeeringConnectionV1,
    ClusterPeeringV1,
    ClusterV1,
)
from reconcile.gql_definitions.terraform_tgw_attachments.aws_accounts import (
    AWSAccountV1,
)
from reconcile.terraform_tgw_attachments import Accepter, DesiredStateItem, Requester
from reconcile.utils.gql import GqlApi
from reconcile.utils.runtime.integration import ShardedRunProposal
from reconcile.utils.secret_reader import SecretReaderBase

QONTRACT_INTEGRATION = "terraform_tgw_attachments"


@pytest.fixture
def account_builder(
    gql_class_factory: Callable[..., AWSAccountV1],
) -> Callable[..., AWSAccountV1]:
    def builder(
        name: str,
        uid: str,
        terraform_username: str,
    ) -> AWSAccountV1:
        return gql_class_factory(
            AWSAccountV1,
            {
                "name": name,
                "uid": uid,
                "terraformUsername": terraform_username,
                "accountOwners": [],
                "automationToken": {},
                "premiumSupport": False,
            },
        )

    return builder


@pytest.fixture
def connection_account_builder(
    gql_class_factory: Callable[..., ClusterPeeringConnectionAccountTGWV1_AWSAccountV1],
) -> Callable[..., ClusterPeeringConnectionAccountTGWV1_AWSAccountV1]:
    def builder(
        name: str,
        uid: str,
        terraform_username: str,
    ) -> ClusterPeeringConnectionAccountTGWV1_AWSAccountV1:
        return gql_class_factory(
            ClusterPeeringConnectionAccountTGWV1_AWSAccountV1,
            {
                "name": name,
                "uid": uid,
                "terraformUsername": terraform_username,
                "automationToken": {},
            },
        )

    return builder


@pytest.fixture
def tgw_account(account_builder: Callable[..., AWSAccountV1]) -> AWSAccountV1:
    return account_builder(
        name="tgw_account",
        uid="tgw-account-uid",
        terraform_username="tgw-account-terraform-username",
    )


@pytest.fixture
def tgw_connection_account(
    connection_account_builder: Callable[
        ..., ClusterPeeringConnectionAccountTGWV1_AWSAccountV1
    ],
    tgw_account: AWSAccountV1,
) -> ClusterPeeringConnectionAccountTGWV1_AWSAccountV1:
    return connection_account_builder(
        name=tgw_account.name,
        uid=tgw_account.uid,
        terraform_username=tgw_account.terraform_username,
    )


@pytest.fixture
def vpc_account(account_builder: Callable[..., AWSAccountV1]) -> AWSAccountV1:
    return account_builder(
        name="vpc_account",
        uid="vpc-account-uid",
        terraform_username="vpc-account-terraform-username",
    )


@pytest.fixture
def vpc_connection_account(
    connection_account_builder: Callable[
        ..., ClusterPeeringConnectionAccountTGWV1_AWSAccountV1
    ],
    vpc_account: AWSAccountV1,
) -> ClusterPeeringConnectionAccountTGWV1_AWSAccountV1:
    return connection_account_builder(
        name=vpc_account.name,
        uid=vpc_account.uid,
        terraform_username=vpc_account.terraform_username,
    )


@pytest.fixture
def additional_tgw_account(
    account_builder: Callable[..., AWSAccountV1],
) -> AWSAccountV1:
    return account_builder(
        name="additional_tgw_account",
        uid="additional_tgw-account-uid",
        terraform_username="additional_tgw-account-terraform-username",
    )


@pytest.fixture
def additional_tgw_connection_account(
    connection_account_builder: Callable[
        ..., ClusterPeeringConnectionAccountTGWV1_AWSAccountV1
    ],
    additional_tgw_account: AWSAccountV1,
) -> ClusterPeeringConnectionAccountTGWV1_AWSAccountV1:
    return connection_account_builder(
        name=additional_tgw_account.name,
        uid=additional_tgw_account.uid,
        terraform_username=additional_tgw_account.terraform_username,
    )


@pytest.fixture
def peering_connection_builder(
    gql_class_factory: Callable[..., ClusterPeeringConnectionAccountTGWV1],
) -> Callable[..., ClusterPeeringConnectionAccountTGWV1]:
    def builder(
        name: str,
        provider: str,
        manage_routes: bool = False,
        account: ClusterPeeringConnectionAccountTGWV1_AWSAccountV1 | None = None,
        assume_role: str | None = None,
        cidr_block: str | None = None,
        delete: bool | None = None,
    ) -> ClusterPeeringConnectionAccountTGWV1:
        return gql_class_factory(
            ClusterPeeringConnectionAccountTGWV1,
            {
                "name": name,
                "provider": provider,
                "manageRoutes": manage_routes,
                "account": account.dict(by_alias=True) if account is not None else None,
                "assumeRole": assume_role,
                "cidrBlock": cidr_block,
                "delete": delete,
            },
        )

    return builder


@pytest.fixture
def account_tgw_connection(
    peering_connection_builder: Callable[..., ClusterPeeringConnectionAccountTGWV1],
    tgw_connection_account: ClusterPeeringConnectionAccountTGWV1_AWSAccountV1,
) -> ClusterPeeringConnectionAccountTGWV1:
    return peering_connection_builder(
        name="account_tgw_connection",
        provider="account-tgw",
        manage_routes=True,
        account=tgw_connection_account,
        assume_role=None,
        cidr_block="172.16.0.0/16",
        delete=False,
    )


@pytest.fixture
def additional_account_tgw_connection(
    peering_connection_builder: Callable[..., ClusterPeeringConnectionAccountTGWV1],
    additional_tgw_connection_account: ClusterPeeringConnectionAccountTGWV1_AWSAccountV1,
) -> ClusterPeeringConnectionAccountTGWV1:
    return peering_connection_builder(
        name="additional_account_tgw_connection",
        provider="account-tgw",
        manage_routes=True,
        account=additional_tgw_connection_account,
        assume_role=None,
        cidr_block="172.16.0.0/16",
        delete=False,
    )


@pytest.fixture
def account_vpc_connection(
    peering_connection_builder: Callable[..., ClusterPeeringConnectionAccountTGWV1],
    vpc_connection_account: ClusterPeeringConnectionAccountTGWV1_AWSAccountV1,
) -> ClusterPeeringConnectionAccountTGWV1:
    return peering_connection_builder(
        name="account_vpc_connection",
        provider="account-vpc",
        account=vpc_connection_account,
    )


@pytest.fixture
def cluster_builder(
    gql_class_factory: Callable[..., ClusterV1],
) -> Callable[..., ClusterV1]:
    def builder(
        name: str,
        ocm: dict,
        region: str,
        vpc_cidr: str,
        peering: ClusterPeeringV1,
    ) -> ClusterV1:
        return gql_class_factory(
            ClusterV1,
            {
                "name": name,
                "ocm": ocm,
                "spec": {
                    "region": region,
                },
                "network": {"vpc": vpc_cidr},
                "peering": peering,
            },
        )

    return builder


@pytest.fixture
def peering_builder(
    gql_class_factory: Callable[..., ClusterPeeringV1],
) -> Callable[..., ClusterPeeringV1]:
    def builder(
        connections: list[
            ClusterPeeringConnectionAccountTGWV1
            | ClusterPeeringConnectionAccountV1
            | ClusterPeeringConnectionAccountVPCMeshV1
            | ClusterPeeringConnectionClusterRequesterV1
            | ClusterPeeringConnectionV1
        ],
    ) -> ClusterPeeringV1:
        return gql_class_factory(
            ClusterPeeringV1,
            {
                "connections": connections,
            },
        )

    return builder


@pytest.fixture
def cluster_with_tgw_connection(
    cluster_builder: Callable[..., ClusterV1],
    peering_builder: Callable[..., ClusterPeeringV1],
    account_tgw_connection: ClusterPeeringConnectionAccountTGWV1,
) -> ClusterV1:
    return cluster_builder(
        name="cluster_with_tgw_connection",
        ocm={
            "name": "cluster_with_tgw_connection-ocm",
            "environment": {"accessTokenClientSecret": {}},
        },
        region="us-east-1",
        vpc_cidr="10.0.0.0/16",
        peering=peering_builder([
            account_tgw_connection,
        ]),
    )


@pytest.fixture
def cluster_with_2_tgw_connections(
    cluster_builder: Callable[..., ClusterV1],
    peering_builder: Callable[..., ClusterPeeringV1],
    account_tgw_connection: ClusterPeeringConnectionAccountTGWV1,
    additional_account_tgw_connection: ClusterPeeringConnectionAccountTGWV1,
) -> ClusterV1:
    return cluster_builder(
        name="cluster_with_2_tgw_connections",
        ocm={
            "name": "cluster_with_2_tgw_connections-ocm",
            "environment": {"accessTokenClientSecret": {}},
        },
        region="us-east-1",
        vpc_cidr="10.0.0.0/16",
        peering=peering_builder([
            account_tgw_connection,
            additional_account_tgw_connection,
        ]),
    )


@pytest.fixture
def additional_cluster_with_tgw_connection(
    cluster_builder: Callable[..., ClusterV1],
    peering_builder: Callable[..., ClusterPeeringV1],
    additional_account_tgw_connection: ClusterPeeringConnectionAccountTGWV1,
) -> ClusterV1:
    return cluster_builder(
        name="additional_cluster_with_tgw_connection",
        ocm={
            "name": "additional_cluster_with_tgw_connection-ocm",
            "environment": {"accessTokenClientSecret": {}},
        },
        region="us-east-1",
        vpc_cidr="10.0.0.0/16",
        peering=peering_builder([
            additional_account_tgw_connection,
        ]),
    )


@pytest.fixture
def cluster_with_duplicate_tgw_connections(
    cluster_builder: Callable[..., ClusterV1],
    peering_builder: Callable[..., ClusterPeeringV1],
    account_tgw_connection: ClusterPeeringConnectionAccountTGWV1,
) -> ClusterV1:
    return cluster_builder(
        name="cluster_with_duplicate_tgw_connections",
        ocm={
            "name": "cluster_with_duplicate_tgw_connections-ocm",
            "environment": {"accessTokenClientSecret": {}},
        },
        region="us-east-1",
        vpc_cidr="10.0.0.0/16",
        peering=peering_builder([
            account_tgw_connection,
            account_tgw_connection,
        ]),
    )


@pytest.fixture
def cluster_with_vpc_connection(
    cluster_builder: Callable[..., ClusterV1],
    peering_builder: Callable[..., ClusterPeeringV1],
    account_vpc_connection: ClusterPeeringConnectionAccountTGWV1,
) -> ClusterV1:
    return cluster_builder(
        name="cluster_with_vpc_connection",
        ocm={
            "name": "cluster_with_vpc_connection-ocm",
            "environment": {"accessTokenClientSecret": {}},
        },
        region="us-east-1",
        vpc_cidr="10.0.0.1/16",
        peering=peering_builder([
            account_vpc_connection,
        ]),
    )


@pytest.fixture
def cluster_with_mixed_connections(
    cluster_builder: Callable[..., ClusterV1],
    peering_builder: Callable[..., ClusterPeeringV1],
    account_tgw_connection: ClusterPeeringConnectionAccountTGWV1,
    account_vpc_connection: ClusterPeeringConnectionAccountTGWV1,
) -> ClusterV1:
    return cluster_builder(
        name="cluster_with_mixed_connections",
        ocm={
            "name": "cluster_with_mixed_connections-ocm",
            "environment": {"accessTokenClientSecret": {}},
        },
        region="us-east-1",
        vpc_cidr="10.0.0.2/16",
        peering=peering_builder([
            account_tgw_connection,
            account_vpc_connection,
        ]),
    )


@pytest.fixture
def tgw() -> dict:
    return {
        "tgw_id": "tgw-1",
        "tgw_arn": "tgw-arn-1",
        "region": "us-west-1",
        "routes": [],
        "rules": [],
        "hostedzones": None,
    }


@pytest.fixture
def vpc_details() -> dict:
    return {
        "vpc_id": "vpc-id-1",
        "route_table_ids": ["rtb-1"],
        "subnets_id_az": [{"az": "us-east-1a", "id": "subnet-1"}],
    }


@pytest.fixture
def assume_role() -> str:
    return "some-role"


@pytest.fixture
def app_interface_vault_settings(
    gql_class_factory: Callable[..., AppInterfaceSettingsV1],
) -> AppInterfaceSettingsV1:
    return gql_class_factory(
        AppInterfaceSettingsV1,
        {"vault": True},
    )


def build_expected_tgw_account(
    connection: ClusterPeeringConnectionAccountTGWV1,
    tgw: Mapping,
) -> dict:
    return {
        "name": connection.account.name,
        "uid": connection.account.uid,
        "assume_role": None,
        "assume_region": tgw["region"],
        "assume_cidr": connection.cidr_block,
    }


def build_expected_cluster_account(
    cluster: ClusterV1,
    connection: ClusterPeeringConnectionAccountTGWV1,
    assume_role: str,
) -> dict:
    return {
        "name": connection.account.name,
        "uid": connection.account.uid,
        "assume_role": assume_role,
        "assume_region": cluster.spec.region if cluster.spec is not None else "",
        "assume_cidr": cluster.network.vpc if cluster.network is not None else "",
    }


def build_expected_desired_state_item(
    cluster: ClusterV1,
    connection: ClusterPeeringConnectionAccountTGWV1,
    tgw: Mapping,
    vpc_details: Mapping,
    expected_tgw_account: Mapping,
    expected_cluster_account: Mapping,
) -> DesiredStateItem:
    return DesiredStateItem(
        connection_provider="account-tgw",
        connection_name=f"{connection.name}_{expected_tgw_account['name']}-{tgw['tgw_id']}",
        infra_acount_name=expected_tgw_account["name"],
        requester=Requester(
            tgw_id=tgw["tgw_id"],
            tgw_arn=tgw["tgw_arn"],
            region=tgw["region"],
            routes=tgw["routes"],
            rules=tgw["rules"],
            hostedzones=tgw["hostedzones"],
            cidr_block=connection.cidr_block,
            account=expected_tgw_account,
        ),
        accepter=Accepter(
            vpc_id=vpc_details["vpc_id"],
            region=cluster.spec.region if cluster.spec is not None else "",
            cidr_block=cluster.network.vpc if cluster.network is not None else "",
            route_table_ids=vpc_details["route_table_ids"],
            subnets_id_az=vpc_details["subnets_id_az"],
            account=expected_cluster_account,
        ),
        deleted=connection.delete,
    )


def _setup_mocks(
    mocker: MockerFixture,
    vault_settings: AppInterfaceSettingsV1,
    clusters: Iterable[ClusterV1] | None = None,
    accounts: Iterable[AWSAccountV1] | None = None,
    vpc_details: Mapping | None = None,
    tgws: Iterable | None = None,
    assume_role: str | None = None,
    feature_toggle_state: bool = True,
) -> dict:
    mocked_gql_api = create_autospec(GqlApi)
    mocker.patch(
        "reconcile.terraform_tgw_attachments.gql"
    ).get_api.return_value = mocked_gql_api
    mocked_get_clusters_with_peering = mocker.patch(
        "reconcile.terraform_tgw_attachments.get_clusters_with_peering"
    )
    mocked_get_clusters_with_peering.return_value = clusters or []

    mocked_get_app_interface_vault_settings = mocker.patch(
        "reconcile.terraform_tgw_attachments.get_app_interface_vault_settings"
    )
    mocked_get_app_interface_vault_settings.return_value = vault_settings

    mocked_get_aws_accounts = mocker.patch(
        "reconcile.terraform_tgw_attachments.get_aws_accounts"
    )
    mocked_get_aws_accounts.return_value = accounts or []

    mocked_secret_reader = create_autospec(SecretReaderBase)
    mocker.patch(
        "reconcile.terraform_tgw_attachments.create_secret_reader"
    ).return_value = mocked_secret_reader

    mocked_aws_api = mocker.patch(
        "reconcile.terraform_tgw_attachments.AWSApi", autospec=True
    )
    aws_api = mocked_aws_api.return_value
    vpc = (
        (
            vpc_details["vpc_id"],
            vpc_details["route_table_ids"],
            vpc_details["subnets_id_az"],
            None,
        )
        if vpc_details is not None
        else (None, None, None, None)
    )
    aws_api.get_cluster_vpc_details.return_value = vpc
    aws_api.get_tgws_details.return_value = tgws or []
    mocked_ocm = mocker.patch(
        "reconcile.terraform_tgw_attachments.OCMMap", autospec=True
    )
    mocked_ocm.return_value.get.return_value.get_aws_infrastructure_access_terraform_assume_role.return_value = assume_role
    mocked_ts = mocker.patch(
        "reconcile.terraform_tgw_attachments.Terrascript", autospec=True
    ).return_value
    mocked_ts.dump.return_value = []

    mocked_tf = mocker.patch(
        "reconcile.terraform_tgw_attachments.Terraform", autospec=True
    ).return_value
    mocked_tf.plan.return_value = (False, False)
    mocked_tf.apply.return_value = False
    mocked_tf.apply_count = 0
    get_feature_toggle_state = mocker.patch(
        "reconcile.terraform_tgw_attachments.get_feature_toggle_state",
        return_value=feature_toggle_state,
    )
    mock_extended_early_exit_run = mocker.patch(
        "reconcile.terraform_tgw_attachments.extended_early_exit_run"
    )
    mocked_logging = mocker.patch("reconcile.terraform_tgw_attachments.logging")

    return {
        "tf": mocked_tf,
        "ts": mocked_ts,
        "get_app_interface_vault_settings": mocked_get_app_interface_vault_settings,
        "get_aws_accounts": mocked_get_aws_accounts,
        "get_clusters_with_peering": mocked_get_clusters_with_peering,
        "secret_reader": mocked_secret_reader,
        "ocm": mocked_ocm,
        "aws_api": mocked_aws_api,
        "gql_api": mocked_gql_api,
        "logging": mocked_logging,
        "extended_early_exit_run": mock_extended_early_exit_run,
        "get_feature_toggle_state": get_feature_toggle_state,
    }


def test_with_extended_early_exit_enabled(
    mocker: MockerFixture,
    app_interface_vault_settings: AppInterfaceSettingsV1,
    cluster_with_tgw_connection: ClusterV1,
    tgw_account: AWSAccountV1,
    tgw: Mapping,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    mocks = _setup_mocks(
        mocker,
        vault_settings=app_interface_vault_settings,
        clusters=[cluster_with_tgw_connection],
        accounts=[tgw_account],
        vpc_details=vpc_details,
        tgws=[tgw],
        assume_role=assume_role,
    )
    expected_params = integ.RunnerParams(
        terraform_client=mocks["tf"],
        terrascript_client=mocks["ts"],
        dry_run=False,
        enable_deletion=False,
    )

    integ.run(
        False,
        enable_deletion=False,
        enable_extended_early_exit=True,
        extended_early_exit_cache_ttl_seconds=40,
        log_cached_log_output=True,
    )

    mocks["extended_early_exit_run"].assert_called_once_with(
        integration=integ.QONTRACT_INTEGRATION,
        integration_version=integ.QONTRACT_INTEGRATION_VERSION,
        dry_run=False,
        shard="",
        cache_source=integ.CacheSource(
            terraform_configurations=mocks["ts"].terraform_configurations.return_value
        ),
        ttl_seconds=40,
        logger=mocks["logging"].getLogger.return_value,
        runner=integ.runner,
        runner_params=expected_params,
        secret_reader=mocks["secret_reader"],
        log_cached_log_output=True,
    )


def test_with_extended_early_exit_disabled(
    mocker: MockerFixture,
    app_interface_vault_settings: AppInterfaceSettingsV1,
    cluster_with_tgw_connection: ClusterV1,
    tgw_account: AWSAccountV1,
    tgw: Mapping,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    mocks = _setup_mocks(
        mocker,
        vault_settings=app_interface_vault_settings,
        clusters=[cluster_with_tgw_connection],
        accounts=[tgw_account],
        vpc_details=vpc_details,
        tgws=[tgw],
        assume_role=assume_role,
    )
    integ.run(
        False,
        enable_deletion=False,
        enable_extended_early_exit=False,
    )
    mocks["extended_early_exit_run"].assert_not_called()
    mocks["get_app_interface_vault_settings"].assert_called_once_with()
    mocks["get_clusters_with_peering"].assert_called_once_with(mocks["gql_api"])
    mocks["get_aws_accounts"].assert_called_once_with(mocks["gql_api"])
    mocks["tf"].plan.assert_called_once_with(False)
    mocks["tf"].apply.assert_called_once()


def test_with_feature_flag_disabled(
    mocker: MockerFixture,
    app_interface_vault_settings: AppInterfaceSettingsV1,
    cluster_with_tgw_connection: ClusterV1,
    tgw_account: AWSAccountV1,
    tgw: Mapping,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    mocks = _setup_mocks(
        mocker,
        vault_settings=app_interface_vault_settings,
        clusters=[cluster_with_tgw_connection],
        accounts=[tgw_account],
        vpc_details=vpc_details,
        tgws=[tgw],
        assume_role=assume_role,
        feature_toggle_state=False,
    )
    integ.run(
        False,
        enable_deletion=False,
        enable_extended_early_exit=True,
        extended_early_exit_cache_ttl_seconds=40,
        log_cached_log_output=True,
    )
    mocks["extended_early_exit_run"].assert_not_called()
    mocks["get_app_interface_vault_settings"].assert_called_once_with()
    mocks["get_clusters_with_peering"].assert_called_once_with(mocks["gql_api"])
    mocks["get_aws_accounts"].assert_called_once_with(mocks["gql_api"])
    mocks["tf"].plan.assert_called_once_with(False)
    mocks["tf"].apply.assert_called_once()


def test_empty_run(
    mocker: MockerFixture,
    app_interface_vault_settings: AppInterfaceSettingsV1,
) -> None:
    mocks = _setup_mocks(
        mocker,
        vault_settings=app_interface_vault_settings,
    )

    integ.run(False, enable_deletion=False)

    mocks["logging"].warning.assert_called_once_with(
        "No participating AWS accounts found, consider disabling this integration, account name: None"
    )
    mocks["get_clusters_with_peering"].assert_called_once_with(mocks["gql_api"])
    mocks["get_aws_accounts"].assert_called_once_with(mocks["gql_api"])
    mocks["get_app_interface_vault_settings"].assert_not_called()
    mocks["tf"].plan.assert_not_called()
    mocks["tf"].apply.assert_not_called()


def test_dry_run(
    mocker: MockerFixture,
    app_interface_vault_settings: AppInterfaceSettingsV1,
    cluster_with_tgw_connection: ClusterV1,
    tgw_account: AWSAccountV1,
    tgw: Mapping,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    mocks = _setup_mocks(
        mocker,
        vault_settings=app_interface_vault_settings,
        clusters=[cluster_with_tgw_connection],
        accounts=[tgw_account],
        vpc_details=vpc_details,
        tgws=[tgw],
        assume_role=assume_role,
    )

    integ.run(True, enable_deletion=False)

    mocks["get_app_interface_vault_settings"].assert_called_once_with()
    mocks["get_clusters_with_peering"].assert_called_once_with(mocks["gql_api"])
    mocks["get_aws_accounts"].assert_called_once_with(mocks["gql_api"])
    mocks["tf"].plan.assert_called_once_with(False)
    mocks["tf"].apply.assert_not_called()


def test_non_dry_run(
    mocker: MockerFixture,
    app_interface_vault_settings: AppInterfaceSettingsV1,
    cluster_with_tgw_connection: ClusterV1,
    tgw_account: AWSAccountV1,
    tgw: Mapping,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    mocks = _setup_mocks(
        mocker,
        vault_settings=app_interface_vault_settings,
        clusters=[cluster_with_tgw_connection],
        accounts=[tgw_account],
        vpc_details=vpc_details,
        tgws=[tgw],
        assume_role=assume_role,
    )

    integ.run(False, enable_deletion=False)

    mocks["get_app_interface_vault_settings"].assert_called_once_with()
    mocks["get_clusters_with_peering"].assert_called_once_with(mocks["gql_api"])
    mocks["get_aws_accounts"].assert_called_once_with(mocks["gql_api"])
    mocks["tf"].plan.assert_called_once_with(False)
    mocks["tf"].apply.assert_called_once()


def test_run_when_cluster_with_tgw_connection(
    mocker: MockerFixture,
    app_interface_vault_settings: AppInterfaceSettingsV1,
    cluster_with_tgw_connection: ClusterV1,
    account_tgw_connection: ClusterPeeringConnectionAccountTGWV1,
    tgw_account: AWSAccountV1,
    tgw: Mapping,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    mocks = _setup_mocks(
        mocker,
        vault_settings=app_interface_vault_settings,
        clusters=[cluster_with_tgw_connection],
        accounts=[tgw_account],
        vpc_details=vpc_details,
        tgws=[tgw],
        assume_role=assume_role,
    )

    integ.run(True)

    expected_tgw_account = build_expected_tgw_account(
        connection=account_tgw_connection,
        tgw=tgw,
    )
    expected_cluster_account = build_expected_cluster_account(
        cluster=cluster_with_tgw_connection,
        connection=account_tgw_connection,
        assume_role=assume_role,
    )
    expected_desired_state_item = build_expected_desired_state_item(
        cluster=cluster_with_tgw_connection,
        connection=account_tgw_connection,
        tgw=tgw,
        vpc_details=vpc_details,
        expected_tgw_account=expected_tgw_account,
        expected_cluster_account=expected_cluster_account,
    )

    mocks["aws_api"].assert_called_once_with(
        1,
        [tgw_account.dict(by_alias=True)],
        secret_reader=mocks["secret_reader"],
        init_users=False,
    )
    mocks["ocm"].assert_called_once_with(
        clusters=[cluster_with_tgw_connection.dict(by_alias=True)],
        integration=QONTRACT_INTEGRATION,
        settings=app_interface_vault_settings.dict(by_alias=True),
    )
    mocks["ts"].populate_additional_providers.assert_called_once_with(
        tgw_account.name, [expected_cluster_account]
    )
    mocks["ts"].populate_tgw_attachments.assert_called_once_with([
        expected_desired_state_item
    ])


def test_run_when_cluster_with_mixed_connections(
    mocker: MockerFixture,
    app_interface_vault_settings: AppInterfaceSettingsV1,
    cluster_with_mixed_connections: ClusterV1,
    account_tgw_connection: ClusterPeeringConnectionAccountTGWV1,
    tgw_account: AWSAccountV1,
    vpc_account: AWSAccountV1,
    tgw: Mapping,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    mocks = _setup_mocks(
        mocker,
        vault_settings=app_interface_vault_settings,
        clusters=[cluster_with_mixed_connections],
        accounts=[tgw_account, vpc_account],
        vpc_details=vpc_details,
        tgws=[tgw],
        assume_role=assume_role,
    )

    integ.run(True)

    expected_tgw_account = build_expected_tgw_account(
        connection=account_tgw_connection,
        tgw=tgw,
    )
    expected_cluster_account = build_expected_cluster_account(
        cluster=cluster_with_mixed_connections,
        connection=account_tgw_connection,
        assume_role=assume_role,
    )
    expected_desired_state_item = build_expected_desired_state_item(
        cluster=cluster_with_mixed_connections,
        connection=account_tgw_connection,
        tgw=tgw,
        vpc_details=vpc_details,
        expected_tgw_account=expected_tgw_account,
        expected_cluster_account=expected_cluster_account,
    )

    mocks["aws_api"].assert_called_once_with(
        1,
        [tgw_account.dict(by_alias=True), vpc_account.dict(by_alias=True)],
        secret_reader=mocks["secret_reader"],
        init_users=False,
    )
    mocks["ocm"].assert_called_once_with(
        clusters=[cluster_with_mixed_connections.dict(by_alias=True)],
        integration=QONTRACT_INTEGRATION,
        settings=app_interface_vault_settings.dict(by_alias=True),
    )
    mocks["ts"].populate_additional_providers.assert_called_once_with(
        tgw_account.name, [expected_cluster_account]
    )
    mocks["ts"].populate_tgw_attachments.assert_called_once_with([
        expected_desired_state_item
    ])


def test_run_when_cluster_with_vpc_connection_only(
    mocker: MockerFixture,
    app_interface_vault_settings: AppInterfaceSettingsV1,
    cluster_with_vpc_connection: ClusterV1,
    vpc_account: AWSAccountV1,
) -> None:
    mocks = _setup_mocks(
        mocker,
        vault_settings=app_interface_vault_settings,
        clusters=[cluster_with_vpc_connection],
        accounts=[vpc_account],
    )

    integ.run(True)

    mocks["aws_api"].assert_not_called()
    mocks["ocm"].assert_not_called()
    mocks["ts"].populate_additional_providers.assert_not_called()
    mocks["ts"].populate_tgw_attachments.assert_not_called()
    mocks["tf"].plan.assert_not_called()
    mocks["tf"].apply.assert_not_called()


def test_run_with_multiple_clusters(
    mocker: MockerFixture,
    app_interface_vault_settings: AppInterfaceSettingsV1,
    cluster_with_tgw_connection: ClusterV1,
    cluster_with_vpc_connection: ClusterV1,
    account_tgw_connection: ClusterPeeringConnectionAccountTGWV1,
    account_vpc_connection: ClusterPeeringConnectionAccountTGWV1,
    tgw_account: AWSAccountV1,
    vpc_account: AWSAccountV1,
    tgw: Mapping,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    mocks = _setup_mocks(
        mocker,
        vault_settings=app_interface_vault_settings,
        clusters=[cluster_with_tgw_connection, cluster_with_vpc_connection],
        accounts=[tgw_account, vpc_account],
        vpc_details=vpc_details,
        tgws=[tgw],
        assume_role=assume_role,
    )

    integ.run(True)

    expected_tgw_account = build_expected_tgw_account(
        connection=account_tgw_connection,
        tgw=tgw,
    )
    expected_cluster_account = build_expected_cluster_account(
        cluster=cluster_with_tgw_connection,
        connection=account_tgw_connection,
        assume_role=assume_role,
    )
    expected_desired_state_item = build_expected_desired_state_item(
        cluster=cluster_with_tgw_connection,
        connection=account_tgw_connection,
        tgw=tgw,
        vpc_details=vpc_details,
        expected_tgw_account=expected_tgw_account,
        expected_cluster_account=expected_cluster_account,
    )

    mocks["aws_api"].assert_called_once_with(
        1,
        [tgw_account.dict(by_alias=True), vpc_account.dict(by_alias=True)],
        secret_reader=mocks["secret_reader"],
        init_users=False,
    )
    mocks["ocm"].assert_called_once_with(
        clusters=[cluster_with_tgw_connection.dict(by_alias=True)],
        integration=QONTRACT_INTEGRATION,
        settings=app_interface_vault_settings.dict(by_alias=True),
    )
    mocks["ts"].populate_additional_providers.assert_called_once_with(
        tgw_account.name, [expected_cluster_account]
    )
    mocks["ts"].populate_tgw_attachments.assert_called_once_with([
        expected_desired_state_item
    ])


def test_run_with_account_name_for_multiple_clusters(
    mocker: MockerFixture,
    app_interface_vault_settings: AppInterfaceSettingsV1,
    cluster_with_tgw_connection: ClusterV1,
    additional_cluster_with_tgw_connection: ClusterV1,
    account_tgw_connection: ClusterPeeringConnectionAccountTGWV1,
    tgw_account: AWSAccountV1,
    tgw: Mapping,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    mocks = _setup_mocks(
        mocker,
        vault_settings=app_interface_vault_settings,
        clusters=[cluster_with_tgw_connection, additional_cluster_with_tgw_connection],
        accounts=[tgw_account],
        vpc_details=vpc_details,
        tgws=[tgw],
        assume_role=assume_role,
    )

    integ.run(True, account_name=tgw_account.name)

    expected_tgw_account = build_expected_tgw_account(
        connection=account_tgw_connection,
        tgw=tgw,
    )
    expected_cluster_account = build_expected_cluster_account(
        cluster=cluster_with_tgw_connection,
        connection=account_tgw_connection,
        assume_role=assume_role,
    )
    expected_desired_state_item = build_expected_desired_state_item(
        cluster=cluster_with_tgw_connection,
        connection=account_tgw_connection,
        tgw=tgw,
        vpc_details=vpc_details,
        expected_tgw_account=expected_tgw_account,
        expected_cluster_account=expected_cluster_account,
    )

    mocks["get_aws_accounts"].assert_called_once_with(mocks["gql_api"])
    mocks["aws_api"].assert_called_once_with(
        1,
        [tgw_account.dict(by_alias=True)],
        secret_reader=mocks["secret_reader"],
        init_users=False,
    )
    mocks["ocm"].assert_called_once_with(
        clusters=[cluster_with_tgw_connection.dict(by_alias=True)],
        integration=QONTRACT_INTEGRATION,
        settings=app_interface_vault_settings.dict(by_alias=True),
    )
    mocks["ts"].populate_additional_providers.assert_called_once_with(
        tgw_account.name, [expected_cluster_account]
    )
    mocks["ts"].populate_tgw_attachments.assert_called_once_with([
        expected_desired_state_item
    ])


def test_run_with_account_name_for_multiple_connections(
    mocker: MockerFixture,
    app_interface_vault_settings: AppInterfaceSettingsV1,
    cluster_with_2_tgw_connections: ClusterV1,
    account_tgw_connection: ClusterPeeringConnectionAccountTGWV1,
    tgw_account: AWSAccountV1,
    tgw: Mapping,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    mocks = _setup_mocks(
        mocker,
        vault_settings=app_interface_vault_settings,
        clusters=[cluster_with_2_tgw_connections],
        accounts=[tgw_account],
        vpc_details=vpc_details,
        tgws=[tgw],
        assume_role=assume_role,
    )

    integ.run(True, account_name=tgw_account.name)

    expected_tgw_account = build_expected_tgw_account(
        connection=account_tgw_connection,
        tgw=tgw,
    )
    expected_cluster_account = build_expected_cluster_account(
        cluster=cluster_with_2_tgw_connections,
        connection=account_tgw_connection,
        assume_role=assume_role,
    )
    expected_desired_state_item = build_expected_desired_state_item(
        cluster=cluster_with_2_tgw_connections,
        connection=account_tgw_connection,
        tgw=tgw,
        vpc_details=vpc_details,
        expected_tgw_account=expected_tgw_account,
        expected_cluster_account=expected_cluster_account,
    )

    mocks["get_aws_accounts"].assert_called_once_with(mocks["gql_api"])
    mocks["aws_api"].assert_called_once_with(
        1,
        [tgw_account.dict(by_alias=True)],
        secret_reader=mocks["secret_reader"],
        init_users=False,
    )
    mocks["ocm"].assert_called_once_with(
        clusters=[cluster_with_2_tgw_connections.dict(by_alias=True)],
        integration=QONTRACT_INTEGRATION,
        settings=app_interface_vault_settings.dict(by_alias=True),
    )
    mocks["ts"].populate_additional_providers.assert_called_once_with(
        tgw_account.name, [expected_cluster_account]
    )
    mocks["ts"].populate_tgw_attachments.assert_called_once_with([
        expected_desired_state_item
    ])


def test_duplicate_tgw_connection_names(
    mocker: MockerFixture,
    app_interface_vault_settings: AppInterfaceSettingsV1,
    cluster_with_duplicate_tgw_connections: ClusterV1,
    tgw_account: AWSAccountV1,
    tgw: AWSAccountV1,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    _setup_mocks(
        mocker,
        vault_settings=app_interface_vault_settings,
        clusters=[cluster_with_duplicate_tgw_connections],
        accounts=[tgw_account],
        vpc_details=vpc_details,
        tgws=[tgw],
        assume_role=assume_role,
    )

    with pytest.raises(integ.ValidationError) as e:
        integ.run(True)

    assert "duplicate tgw connection names found" == str(e.value)


def test_missing_vpc_id(
    mocker: MockerFixture,
    app_interface_vault_settings: AppInterfaceSettingsV1,
    cluster_with_tgw_connection: ClusterV1,
    tgw_account: AWSAccountV1,
    tgw: Mapping,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    _setup_mocks(
        mocker,
        vault_settings=app_interface_vault_settings,
        clusters=[cluster_with_tgw_connection],
        accounts=[tgw_account],
        vpc_details=None,
        tgws=[tgw],
        assume_role=assume_role,
    )

    with pytest.raises(RuntimeError) as e:
        integ.run(True)

    assert "Could not find VPC ID for cluster" == str(e.value)


def test_error_in_tf_plan(
    mocker: MockerFixture,
    app_interface_vault_settings: AppInterfaceSettingsV1,
    cluster_with_tgw_connection: ClusterV1,
    tgw_account: AWSAccountV1,
    account_tgw_connection: ClusterPeeringConnectionAccountTGWV1,
    tgw: Mapping,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    mocks = _setup_mocks(
        mocker,
        vault_settings=app_interface_vault_settings,
        clusters=[cluster_with_tgw_connection],
        accounts=[tgw_account],
        vpc_details=vpc_details,
        tgws=[tgw],
        assume_role=assume_role,
    )
    mocks["tf"].plan.return_value = (False, True)

    with pytest.raises(RuntimeError) as e:
        integ.run(True)

    assert "Error running terraform plan" == str(e.value)


def test_disabled_deletions_detected_in_tf_plan(
    mocker: MockerFixture,
    app_interface_vault_settings: AppInterfaceSettingsV1,
    cluster_with_tgw_connection: ClusterV1,
    tgw_account: AWSAccountV1,
    account_tgw_connection: ClusterPeeringConnectionAccountTGWV1,
    tgw: Mapping,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    mocks = _setup_mocks(
        mocker,
        vault_settings=app_interface_vault_settings,
        clusters=[cluster_with_tgw_connection],
        accounts=[tgw_account],
        vpc_details=vpc_details,
        tgws=[tgw],
        assume_role=assume_role,
    )
    mocks["tf"].plan.return_value = (True, False)

    with pytest.raises(RuntimeError) as e:
        integ.run(True)

    assert "Disabled deletions detected running terraform plan" == str(e.value)


def test_error_in_terraform_apply(
    mocker: MockerFixture,
    app_interface_vault_settings: AppInterfaceSettingsV1,
    cluster_with_tgw_connection: ClusterV1,
    account_tgw_connection: ClusterPeeringConnectionAccountTGWV1,
    tgw_account: AWSAccountV1,
    tgw: Mapping,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    mocks = _setup_mocks(
        mocker,
        vault_settings=app_interface_vault_settings,
        clusters=[cluster_with_tgw_connection],
        accounts=[tgw_account],
        vpc_details=vpc_details,
        tgws=[tgw],
        assume_role=assume_role,
    )
    mocks["tf"].apply.return_value = True

    with pytest.raises(RuntimeError) as e:
        integ.run(False)

    assert "Error running terraform apply" == str(e.value)


def test_early_exit_desired_state(
    mocker: MockerFixture,
    app_interface_vault_settings: AppInterfaceSettingsV1,
    cluster_with_tgw_connection: ClusterV1,
    cluster_with_vpc_connection: ClusterV1,
    tgw_account: AWSAccountV1,
    vpc_account: AWSAccountV1,
) -> None:
    _setup_mocks(
        mocker,
        vault_settings=app_interface_vault_settings,
        clusters=[cluster_with_tgw_connection, cluster_with_vpc_connection],
        accounts=[tgw_account, vpc_account],
    )

    desired_state = integ.early_exit_desired_state()

    expected_early_exit_desired_state = {
        "clusters": [cluster_with_tgw_connection.dict(by_alias=True)],
        "accounts": [tgw_account.dict(by_alias=True), vpc_account.dict(by_alias=True)],
    }

    assert desired_state == expected_early_exit_desired_state


def test_desired_state_shard_config() -> None:
    proposal_with_1_shard = ShardedRunProposal(
        proposed_shards={
            "account1",
        }
    )
    proposal_with_2_shards = ShardedRunProposal(
        proposed_shards={
            "account1",
            "account2",
        }
    )
    proposal_with_3_shards = ShardedRunProposal(
        proposed_shards={
            "account1",
            "account2",
            "account3",
        }
    )

    config = integ.desired_state_shard_config()

    assert config.shard_arg_name == "account_name"
    assert config.shard_path_selectors == {
        "accounts[*].name",
        "clusters[*].peering.connections[*].account.name",
    }
    assert config.shard_arg_is_collection is False
    assert config.sharded_run_review(proposal_with_1_shard) is True
    assert config.sharded_run_review(proposal_with_2_shards) is True
    assert config.sharded_run_review(proposal_with_3_shards) is False
