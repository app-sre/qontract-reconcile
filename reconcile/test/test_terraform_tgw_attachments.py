from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from typing import Optional

import pytest
from pytest_mock import MockerFixture

import reconcile.terraform_tgw_attachments as integ


@pytest.fixture
def peering_connection_builder() -> Callable[..., dict]:
    def builder(
        name: str,
        provider: str,
        manage_routes: bool = False,
        account_name: Optional[str] = None,
        account_uid: Optional[str] = None,
        terraform_username: Optional[str] = None,
        assume_role: Optional[str] = None,
        cidr_block: Optional[str] = None,
        deleted: Optional[bool] = None,
    ) -> dict:
        return {
            "name": name,
            "provider": provider,
            "manageRoutes": manage_routes,
            "account": {
                "name": account_name,
                "uid": account_uid,
                "terraformUsername": terraform_username,
            },
            "assumeRole": assume_role,
            "cidrBlock": cidr_block,
            "deleted": deleted,
        }

    return builder


@pytest.fixture
def account_tgw_connection(peering_connection_builder: Callable[..., dict]) -> dict:
    return peering_connection_builder(
        name="account_tgw_connection",
        provider="account-tgw",
        manage_routes=True,
        account_name="tgw_account",
        account_uid="a-uid",
        terraform_username="tf-user",
        assume_role=None,
        cidr_block="172.16.0.0/16",
        deleted=False,
    )


@pytest.fixture
def account_vpc_connection(peering_connection_builder: Callable[..., dict]) -> dict:
    return peering_connection_builder(
        name="account_vpc_connection",
        provider="account-vpc",
    )


@pytest.fixture
def cluster_builder() -> Callable[..., dict]:
    def builder(
        name: str,
        ocm: dict,
        region: str,
        vpc_cidr: str,
        peering: dict,
    ) -> dict:
        return {
            "name": name,
            "ocm": ocm,
            "spec": {
                "region": region,
            },
            "network": {"vpc": vpc_cidr},
            "peering": peering,
        }

    return builder


@pytest.fixture
def cluster_with_tgw_connection(
    cluster_builder: Callable[..., dict],
    account_tgw_connection: dict,
) -> dict:
    return cluster_builder(
        name="cluster_with_tgw_connection",
        ocm={"name": "cluster_with_tgw_connection-ocm"},
        region="us-east-1",
        vpc_cidr="10.0.0.0/16",
        peering={
            "connections": [
                account_tgw_connection,
            ]
        },
    )


@pytest.fixture
def cluster_with_duplicate_tgw_connections(
    cluster_builder: Callable[..., dict],
    account_tgw_connection: dict,
) -> dict:
    return cluster_builder(
        name="cluster_with_duplicate_tgw_connections",
        ocm={"name": "cluster_with_duplicate_tgw_connections-ocm"},
        region="us-east-1",
        vpc_cidr="10.0.0.0/16",
        peering={
            "connections": [
                account_tgw_connection,
                account_tgw_connection,
            ]
        },
    )


@pytest.fixture
def cluster_with_vpc_connection(
    cluster_builder: Callable[..., dict],
    account_vpc_connection: Mapping,
) -> dict:
    return cluster_builder(
        name="cluster_with_vpc_connection",
        ocm={"name": "cluster_with_vpc_connection-ocm"},
        region="us-east-1",
        vpc_cidr="10.0.0.1/16",
        peering={
            "connections": [
                account_vpc_connection,
            ]
        },
    )


@pytest.fixture
def cluster_with_mixed_connections(
    cluster_builder: Callable[..., dict],
    account_tgw_connection: Mapping,
    account_vpc_connection: Mapping,
) -> dict:
    return cluster_builder(
        name="cluster_with_mixed_connections",
        ocm={"name": "cluster_with_mixed_connections-ocm"},
        region="us-east-1",
        vpc_cidr="10.0.0.2/16",
        peering={
            "connections": [
                account_tgw_connection,
                account_vpc_connection,
            ]
        },
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


def _setup_mocks(
    mocker: MockerFixture,
    clusters: Optional[Iterable] = None,
    accounts: Optional[Iterable] = None,
    vpc_details: Optional[Mapping] = None,
    tgws: Optional[Iterable] = None,
    assume_role: Optional[str] = None,
) -> dict:
    mocked_queries = mocker.patch("reconcile.terraform_tgw_attachments.queries")
    mocked_queries.get_secret_reader_settings.return_value = {}
    mocked_queries.get_clusters_with_peering_settings.return_value = clusters or []
    mocked_queries.get_aws_accounts.return_value = accounts or []
    mocked_aws_api = mocker.patch(
        "reconcile.terraform_tgw_attachments.AWSApi", autospec=True
    ).return_value
    with mocked_aws_api as aws_api:
        vpc = (
            (
                vpc_details["vpc_id"],
                vpc_details["route_table_ids"],
                vpc_details["subnets_id_az"],
            )
            if vpc_details is not None
            else (None, None, None)
        )
        aws_api.get_cluster_vpc_details.return_value = vpc
        aws_api.get_tgws_details.return_value = tgws or []
    mocked_ocm = mocker.patch(
        "reconcile.terraform_tgw_attachments.OCMMap", autospec=True
    ).return_value
    mocked_ocm.get.return_value.get_aws_infrastructure_access_terraform_assume_role.return_value = (
        assume_role
    )
    mocked_ts = mocker.patch(
        "reconcile.terraform_tgw_attachments.Terrascript", autospec=True
    ).return_value
    mocked_ts.dump.return_value = []

    mocked_tf = mocker.patch(
        "reconcile.terraform_tgw_attachments.Terraform", autospec=True
    ).return_value
    mocked_tf.plan.return_value = (False, False)
    mocked_tf.apply.return_value = False
    return {
        "tf": mocked_tf,
        "ts": mocked_ts,
        "queries": mocked_queries,
    }


def test_dry_run(mocker: MockerFixture) -> None:
    mocks = _setup_mocks(mocker)

    integ.run(True, enable_deletion=False)

    mocks["queries"].get_secret_reader_settings.assert_called_once_with()
    mocks["queries"].get_clusters_with_peering_settings.assert_called_once_with()
    mocks["queries"].get_aws_accounts.assert_called_once_with(
        terraform_state=True, ecrs=False
    )
    mocks["tf"].plan.assert_called_once_with(False)
    mocks["tf"].apply.assert_not_called()


def test_non_dry_run(mocker: MockerFixture) -> None:
    mocks = _setup_mocks(mocker)

    integ.run(False, enable_deletion=False)

    mocks["queries"].get_secret_reader_settings.assert_called_once_with()
    mocks["queries"].get_clusters_with_peering_settings.assert_called_once_with()
    mocks["queries"].get_aws_accounts.assert_called_once_with(
        terraform_state=True, ecrs=False
    )
    mocks["tf"].plan.assert_called_once_with(False)
    mocks["tf"].apply.assert_called_once()


def test_run_when_cluster_with_tgw_connection(
    mocker: MockerFixture,
    cluster_with_tgw_connection: Mapping,
    account_tgw_connection: Mapping,
    tgw: Mapping,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    mocks = _setup_mocks(
        mocker,
        clusters=[cluster_with_tgw_connection],
        vpc_details=vpc_details,
        tgws=[tgw],
        assume_role=assume_role,
    )

    integ.run(True)

    expected_tgw_account = {
        "name": account_tgw_connection["account"]["name"],
        "uid": account_tgw_connection["account"]["uid"],
        "terraformUsername": account_tgw_connection["account"]["terraformUsername"],
        "assume_role": assume_role,
        "assume_region": cluster_with_tgw_connection["spec"]["region"],
        "assume_cidr": cluster_with_tgw_connection["network"]["vpc"],
    }

    mocks["ts"].populate_additional_providers.assert_called_once_with(
        [expected_tgw_account]
    )
    mocks["ts"].populate_tgw_attachments.assert_called_once_with(
        [
            {
                "connection_provider": "account-tgw",
                "connection_name": f"{account_tgw_connection['name']}_{expected_tgw_account['name']}-{tgw['tgw_id']}",
                "requester": {
                    "tgw_id": tgw["tgw_id"],
                    "tgw_arn": tgw["tgw_arn"],
                    "region": tgw["region"],
                    "routes": tgw["routes"],
                    "rules": tgw["rules"],
                    "hostedzones": tgw["hostedzones"],
                    "cidr_block": account_tgw_connection["cidrBlock"],
                    "account": expected_tgw_account,
                },
                "accepter": {
                    "vpc_id": vpc_details["vpc_id"],
                    "region": cluster_with_tgw_connection["spec"]["region"],
                    "cidr_block": cluster_with_tgw_connection["network"]["vpc"],
                    "route_table_ids": vpc_details["route_table_ids"],
                    "subnets_id_az": vpc_details["subnets_id_az"],
                    "account": expected_tgw_account,
                },
                "deleted": account_tgw_connection["deleted"],
            }
        ]
    )


def test_run_when_cluster_with_mixed_connections(
    mocker: MockerFixture,
    cluster_with_mixed_connections: Mapping,
    account_tgw_connection: Mapping,
    tgw: Mapping,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    mocks = _setup_mocks(
        mocker,
        clusters=[cluster_with_mixed_connections],
        vpc_details=vpc_details,
        tgws=[tgw],
        assume_role=assume_role,
    )

    integ.run(True)

    expected_tgw_account = {
        "name": account_tgw_connection["account"]["name"],
        "uid": account_tgw_connection["account"]["uid"],
        "terraformUsername": account_tgw_connection["account"]["terraformUsername"],
        "assume_role": assume_role,
        "assume_region": cluster_with_mixed_connections["spec"]["region"],
        "assume_cidr": cluster_with_mixed_connections["network"]["vpc"],
    }

    mocks["ts"].populate_additional_providers.assert_called_once_with(
        [expected_tgw_account]
    )
    mocks["ts"].populate_tgw_attachments.assert_called_once_with(
        [
            {
                "connection_provider": "account-tgw",
                "connection_name": f"{account_tgw_connection['name']}_{expected_tgw_account['name']}-{tgw['tgw_id']}",
                "requester": {
                    "tgw_id": tgw["tgw_id"],
                    "tgw_arn": tgw["tgw_arn"],
                    "region": tgw["region"],
                    "routes": tgw["routes"],
                    "rules": tgw["rules"],
                    "hostedzones": tgw["hostedzones"],
                    "cidr_block": account_tgw_connection["cidrBlock"],
                    "account": expected_tgw_account,
                },
                "accepter": {
                    "vpc_id": vpc_details["vpc_id"],
                    "region": cluster_with_mixed_connections["spec"]["region"],
                    "cidr_block": cluster_with_mixed_connections["network"]["vpc"],
                    "route_table_ids": vpc_details["route_table_ids"],
                    "subnets_id_az": vpc_details["subnets_id_az"],
                    "account": expected_tgw_account,
                },
                "deleted": account_tgw_connection["deleted"],
            }
        ]
    )


def test_run_when_cluster_with_vpc_connection_only(
    mocker: MockerFixture,
    cluster_with_vpc_connection: Mapping,
) -> None:
    mocks = _setup_mocks(
        mocker,
        clusters=[cluster_with_vpc_connection],
    )

    integ.run(True)

    mocks["ts"].populate_additional_providers.assert_called_once_with([])
    mocks["ts"].populate_tgw_attachments.assert_called_once_with([])


def test_duplicate_tgw_connection_names(
    mocker: MockerFixture,
    cluster_with_duplicate_tgw_connections: Mapping,
    tgw: Mapping,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    _setup_mocks(
        mocker,
        clusters=[cluster_with_duplicate_tgw_connections],
        vpc_details=vpc_details,
        tgws=[tgw],
        assume_role=assume_role,
    )

    with pytest.raises(integ.ValidationError) as e:
        integ.run(True)

    assert "duplicate tgw connection names found" == str(e.value)


def test_missing_vpc_id(
    mocker: MockerFixture,
    cluster_with_tgw_connection: Mapping,
    tgw: Mapping,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    _setup_mocks(
        mocker,
        clusters=[cluster_with_tgw_connection],
        vpc_details=None,
        tgws=[tgw],
        assume_role=assume_role,
    )

    with pytest.raises(RuntimeError) as e:
        integ.run(True)

    assert "Could not find VPC ID for cluster" == str(e.value)


def test_error_in_tf_plan(
    mocker: MockerFixture,
    cluster_with_tgw_connection: Mapping,
    account_tgw_connection: Mapping,
    tgw: Mapping,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    mocks = _setup_mocks(
        mocker,
        clusters=[cluster_with_tgw_connection],
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
    cluster_with_tgw_connection: Mapping,
    account_tgw_connection: Mapping,
    tgw: Mapping,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    mocks = _setup_mocks(
        mocker,
        clusters=[cluster_with_tgw_connection],
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
    cluster_with_tgw_connection: Mapping,
    account_tgw_connection: Mapping,
    tgw: Mapping,
    vpc_details: Mapping,
    assume_role: str,
) -> None:
    mocks = _setup_mocks(
        mocker,
        clusters=[cluster_with_tgw_connection],
        vpc_details=vpc_details,
        tgws=[tgw],
        assume_role=assume_role,
    )
    mocks["tf"].apply.return_value = True

    with pytest.raises(RuntimeError) as e:
        integ.run(False)

    assert "Error running terraform apply" == str(e.value)
