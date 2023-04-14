import pytest

import reconcile.terraform_tgw_attachments as integ


@pytest.fixture
def peering_connection_builder():
    def builder(
        name,
        provider,
        manage_routes=None,
        account_name=None,
        account_uid=None,
        terraform_username=None,
        assume_role=None,
        cidr_block=None,
        deleted=None,
    ):
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
def account_tgw_connection(peering_connection_builder):
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
def account_vpc_connection(peering_connection_builder):
    return peering_connection_builder(
        name="account_vpc_connection",
        provider="account-vpc",
    )


@pytest.fixture
def cluster_builder():
    def builder(
        name,
        ocm,
        region,
        vpc_cidr,
        peering,
    ):
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
def cluster_with_tgw_connection(cluster_builder, account_tgw_connection):
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
def cluster_with_vpc_connection(cluster_builder, account_vpc_connection):
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
    cluster_builder, account_tgw_connection, account_vpc_connection
):
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
def tgw():
    return {
        "tgw_id": "tgw-1",
        "tgw_arn": "tgw-arn-1",
        "region": "us-west-1",
        "routes": [],
        "rules": [],
        "hostedzones": None,
    }


@pytest.fixture
def vpc_details():
    return {
        "vpc_id": "vpc-id-1",
        "route_table_ids": ["rtb-1"],
        "subnets_id_az": [{"az": "us-east-1a", "id": "subnet-1"}],
    }


@pytest.fixture
def assume_role():
    return "some-role"


def _setup_mocks(
    mocker, clusters=None, accounts=None, vpc=None, tgws=None, assume_role=None
):
    mocker.patch(
        "reconcile.terraform_tgw_attachments.queries.get_secret_reader_settings",
        return_value={},
    )
    mocker.patch(
        "reconcile.terraform_tgw_attachments.queries.get_clusters_with_peering_settings",
        return_value=clusters or [],
    )
    mocker.patch(
        "reconcile.terraform_tgw_attachments.queries.get_aws_accounts",
        return_value=accounts or [],
    )
    mocked_aws_api = mocker.patch(
        "reconcile.terraform_tgw_attachments.AWSApi", autospec=True
    ).return_value
    with mocked_aws_api as aws_api:
        aws_api.get_cluster_vpc_details.return_value = vpc or (None, None, None)
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
    }


def test_dry_run(mocker):
    mocks = _setup_mocks(mocker)

    integ.run(True, enable_deletion=False)

    mocks["tf"].plan.assert_called_once_with(False)
    mocks["tf"].apply.assert_not_called()


def test_non_dry_run(mocker):
    mocks = _setup_mocks(mocker)

    integ.run(False, enable_deletion=False)

    mocks["tf"].plan.assert_called_once_with(False)
    mocks["tf"].apply.assert_called_once()


def test_run_when_cluster_with_tgw_connection(
    mocker,
    cluster_with_tgw_connection,
    account_tgw_connection,
    tgw,
    vpc_details,
    assume_role,
):
    mocks = _setup_mocks(
        mocker,
        clusters=[cluster_with_tgw_connection],
        vpc=(
            vpc_details["vpc_id"],
            vpc_details["route_table_ids"],
            vpc_details["subnets_id_az"],
        ),
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
        [expected_tgw_account, expected_tgw_account]
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
    mocker,
    cluster_with_mixed_connections,
    account_tgw_connection,
    tgw,
    vpc_details,
    assume_role,
):
    mocks = _setup_mocks(
        mocker,
        clusters=[cluster_with_mixed_connections],
        vpc=(
            vpc_details["vpc_id"],
            vpc_details["route_table_ids"],
            vpc_details["subnets_id_az"],
        ),
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
        [expected_tgw_account, expected_tgw_account]
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
    mocker,
    cluster_with_vpc_connection,
):
    mocks = _setup_mocks(
        mocker,
        clusters=[cluster_with_vpc_connection],
    )

    integ.run(True)

    mocks["ts"].populate_additional_providers.assert_called_once_with([])
    mocks["ts"].populate_tgw_attachments.assert_called_once_with([])
