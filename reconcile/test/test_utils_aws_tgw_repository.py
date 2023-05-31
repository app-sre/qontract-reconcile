from collections.abc import (
    Callable,
    Iterable,
)
from typing import (
    Optional,
    Union,
)
from unittest.mock import create_autospec

import pytest
from pytest_mock import MockerFixture

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
from reconcile.utils.aws_tgw_repository import (
    AWSTGWClustersAndAccounts,
    AWSTGWRepository,
)
from reconcile.utils.gql import GqlApi


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
    account_builder: Callable[..., AWSAccountV1]
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
        account: Optional[ClusterPeeringConnectionAccountTGWV1_AWSAccountV1] = None,
        assume_role: Optional[str] = None,
        cidr_block: Optional[str] = None,
        delete: Optional[bool] = None,
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
            Union[
                ClusterPeeringConnectionAccountTGWV1,
                ClusterPeeringConnectionAccountV1,
                ClusterPeeringConnectionAccountVPCMeshV1,
                ClusterPeeringConnectionClusterRequesterV1,
                ClusterPeeringConnectionV1,
            ]
        ]
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
        peering=peering_builder(
            [
                account_tgw_connection,
            ]
        ),
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
        peering=peering_builder(
            [
                account_tgw_connection,
                additional_account_tgw_connection,
            ]
        ),
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
        peering=peering_builder(
            [
                additional_account_tgw_connection,
            ]
        ),
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
        peering=peering_builder(
            [
                account_tgw_connection,
                account_tgw_connection,
            ]
        ),
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
        peering=peering_builder(
            [
                account_vpc_connection,
            ]
        ),
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
        peering=peering_builder(
            [
                account_tgw_connection,
                account_vpc_connection,
            ]
        ),
    )


def _setup_mocks(
    mocker: MockerFixture,
    clusters: Optional[Iterable[ClusterV1]] = None,
    accounts: Optional[Iterable[AWSAccountV1]] = None,
) -> dict:
    mocked_gql_api = create_autospec(GqlApi)
    mocker.patch(
        "reconcile.utils.aws_tgw_repository.gql"
    ).get_api.return_value = mocked_gql_api

    mocked_get_clusters_with_peering = mocker.patch(
        "reconcile.utils.aws_tgw_repository.get_clusters_with_peering"
    )
    mocked_get_clusters_with_peering.return_value = clusters or []

    mocked_get_aws_accounts = mocker.patch(
        "reconcile.utils.aws_tgw_repository.get_aws_accounts"
    )
    mocked_get_aws_accounts.return_value = accounts or []

    return {
        "get_aws_accounts": mocked_get_aws_accounts,
        "get_clusters_with_peering": mocked_get_clusters_with_peering,
        "gql_api": mocked_gql_api,
    }


def test_get_tgw_clusters_and_accounts_when_cluster_with_tgw_connection(
    mocker: MockerFixture,
    cluster_with_tgw_connection: ClusterV1,
    account_tgw_connection: ClusterPeeringConnectionAccountTGWV1,
    tgw_account: AWSAccountV1,
) -> None:
    mocks = _setup_mocks(
        mocker,
        clusters=[cluster_with_tgw_connection],
        accounts=[tgw_account],
    )
    repo = AWSTGWRepository(mocks["gql_api"])

    result = repo.get_tgw_clusters_and_accounts()

    expected_result = AWSTGWClustersAndAccounts(
        clusters=[cluster_with_tgw_connection],
        accounts=[tgw_account],
    )
    assert result == expected_result
    mocks["get_clusters_with_peering"].assert_called_once_with(mocks["gql_api"])
    mocks["get_aws_accounts"].assert_called_once_with(mocks["gql_api"], name=None)


def test_get_tgw_clusters_and_accounts_when_cluster_with_mixed_connections(
    mocker: MockerFixture,
    cluster_with_mixed_connections: ClusterV1,
    account_tgw_connection: ClusterPeeringConnectionAccountTGWV1,
    tgw_account: AWSAccountV1,
    vpc_account: AWSAccountV1,
) -> None:
    mocks = _setup_mocks(
        mocker,
        clusters=[cluster_with_mixed_connections],
        accounts=[tgw_account, vpc_account],
    )
    repo = AWSTGWRepository(mocks["gql_api"])

    result = repo.get_tgw_clusters_and_accounts()

    expected_result = AWSTGWClustersAndAccounts(
        clusters=[cluster_with_mixed_connections],
        accounts=[tgw_account],
    )
    assert result == expected_result
    mocks["get_clusters_with_peering"].assert_called_once_with(mocks["gql_api"])
    mocks["get_aws_accounts"].assert_called_once_with(mocks["gql_api"], name=None)


def test_get_tgw_clusters_and_accounts_when_cluster_with_vpc_connection_only(
    mocker: MockerFixture,
    cluster_with_vpc_connection: ClusterV1,
    vpc_account: AWSAccountV1,
) -> None:
    mocks = _setup_mocks(
        mocker,
        clusters=[cluster_with_vpc_connection],
        accounts=[vpc_account],
    )
    repo = AWSTGWRepository(mocks["gql_api"])

    result = repo.get_tgw_clusters_and_accounts()

    expected_result = AWSTGWClustersAndAccounts(
        clusters=[],
        accounts=[],
    )
    assert result == expected_result
    mocks["get_clusters_with_peering"].assert_called_once_with(mocks["gql_api"])
    mocks["get_aws_accounts"].assert_called_once_with(mocks["gql_api"], name=None)


def test_get_tgw_clusters_and_accounts_with_multiple_clusters(
    mocker: MockerFixture,
    cluster_with_tgw_connection: ClusterV1,
    cluster_with_vpc_connection: ClusterV1,
    account_tgw_connection: ClusterPeeringConnectionAccountTGWV1,
    account_vpc_connection: ClusterPeeringConnectionAccountTGWV1,
    tgw_account: AWSAccountV1,
    vpc_account: AWSAccountV1,
) -> None:
    mocks = _setup_mocks(
        mocker,
        clusters=[cluster_with_tgw_connection, cluster_with_vpc_connection],
        accounts=[tgw_account, vpc_account],
    )
    repo = AWSTGWRepository(mocks["gql_api"])

    result = repo.get_tgw_clusters_and_accounts()

    expected_result = AWSTGWClustersAndAccounts(
        clusters=[cluster_with_tgw_connection],
        accounts=[tgw_account],
    )
    assert result == expected_result
    mocks["get_clusters_with_peering"].assert_called_once_with(mocks["gql_api"])
    mocks["get_aws_accounts"].assert_called_once_with(mocks["gql_api"], name=None)


def test_get_tgw_clusters_and_accounts_with_account_name_for_multiple_clusters(
    mocker: MockerFixture,
    cluster_with_tgw_connection: ClusterV1,
    additional_cluster_with_tgw_connection: ClusterV1,
    account_tgw_connection: ClusterPeeringConnectionAccountTGWV1,
    tgw_account: AWSAccountV1,
) -> None:
    mocks = _setup_mocks(
        mocker,
        clusters=[cluster_with_tgw_connection, additional_cluster_with_tgw_connection],
        accounts=[tgw_account],
    )
    repo = AWSTGWRepository(mocks["gql_api"])

    result = repo.get_tgw_clusters_and_accounts(tgw_account.name)

    expected_result = AWSTGWClustersAndAccounts(
        clusters=[cluster_with_tgw_connection],
        accounts=[tgw_account],
    )
    assert result == expected_result
    mocks["get_clusters_with_peering"].assert_called_once_with(mocks["gql_api"])
    mocks["get_aws_accounts"].assert_called_once_with(
        mocks["gql_api"], name=tgw_account.name
    )


def test_get_tgw_clusters_and_accounts_with_account_name_for_multiple_connections(
    mocker: MockerFixture,
    cluster_with_2_tgw_connections: ClusterV1,
    account_tgw_connection: ClusterPeeringConnectionAccountTGWV1,
    tgw_account: AWSAccountV1,
) -> None:
    mocks = _setup_mocks(
        mocker,
        clusters=[cluster_with_2_tgw_connections],
        accounts=[tgw_account],
    )
    repo = AWSTGWRepository(mocks["gql_api"])

    result = repo.get_tgw_clusters_and_accounts(tgw_account.name)

    expected_result = AWSTGWClustersAndAccounts(
        clusters=[cluster_with_2_tgw_connections],
        accounts=[tgw_account],
    )
    assert result == expected_result
    mocks["get_clusters_with_peering"].assert_called_once_with(mocks["gql_api"])
    mocks["get_aws_accounts"].assert_called_once_with(
        mocks["gql_api"], name=tgw_account.name
    )
