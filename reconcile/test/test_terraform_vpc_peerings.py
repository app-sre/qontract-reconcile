import sys
from typing import Any, Optional, Tuple
import testslide
import pytest

import reconcile.terraform_vpc_peerings as integ
from reconcile.terraform_vpc_peerings import BadTerraformPeeringState
from reconcile.utils import aws_api
import reconcile.utils.terraform_client as terraform
import reconcile.utils.terrascript_client as terrascript
from reconcile import queries
from reconcile.utils import ocm


class MockOCM:
    def __init__(self) -> None:
        self.assumes: dict[str, str] = {}

    def register(
        self, cluster: str, tf_account_id: str, tf_user: str, assume_role: Optional[str]
    ) -> "MockOCM":
        if not assume_role:
            assume_role = f"arn::::{cluster}"
        if not assume_role.startswith("arn:"):
            assume_role = f"arn::::{assume_role}"
        self.assumes[f"{cluster}/{tf_account_id}/{tf_user}"] = assume_role
        return self

    def get_aws_infrastructure_access_terraform_assume_role(
        self, cluster, tf_account_id, tf_user
    ):
        return self.assumes.get(f"{cluster}/{tf_account_id}/{tf_user}")

    def auto_speced_mock(self, mocker) -> ocm.OCM:
        ocm_mock = mocker.patch("reconcile.utils.ocm.OCM", autospec=True).return_value
        ocm_mock.get_aws_infrastructure_access_terraform_assume_role.mock_add_spec(
            ocm.OCM.get_aws_infrastructure_access_terraform_assume_role
        )
        ocm_mock.get_aws_infrastructure_access_terraform_assume_role.side_effect = (
            self.get_aws_infrastructure_access_terraform_assume_role
        )
        return ocm_mock


class MockAWSAPI:
    def __init__(self) -> None:
        self.vpc_details: dict[str, Tuple[str, list[str]]] = {}

    def register(self, vpc: str, vpc_id: str, route_tables: list[str]) -> "MockAWSAPI":
        self.vpc_details[vpc] = (vpc_id, route_tables)
        return self

    def get_cluster_vpc_details(
        self, account: dict[str, Any], route_tables=False, subnets=False
    ) -> Tuple:
        if account["assume_cidr"] in self.vpc_details:
            vpc_id, rt = self.vpc_details[account["assume_cidr"]]
            if not route_tables:
                return vpc_id, None, None
            else:
                return vpc_id, rt, None
        else:
            return None, None, None

    def auto_speced_mock(self, mocker) -> aws_api.AWSApi:
        aws_api_mock = mocker.patch(
            "reconcile.utils.aws_api.AWSApi", autospec=True
        ).return_value
        aws_api_mock.get_cluster_vpc_details.mock_add_spec(
            aws_api.AWSApi.get_cluster_vpc_details
        )
        aws_api_mock.get_cluster_vpc_details.side_effect = self.get_cluster_vpc_details
        return aws_api_mock


def build_cluster(
    name: str,
    vpc: Optional[str] = None,
    read_only_accounts: Optional[list[str]] = None,
    network_mgmt_accounts: Optional[list[str]] = None,
    peering_connections: Optional[list[dict[str, Any]]] = None,
):
    if not vpc:
        vpc = name
    cluster = {
        "name": name,
        "spec": {"region": "region"},
        "network": {"vpc": vpc},
        "peering": {"connections": peering_connections or []},
        "awsInfrastructureManagementAccounts": None,
    }

    if read_only_accounts or network_mgmt_accounts:
        cluster["awsInfrastructureManagementAccounts"] = []
        if read_only_accounts:
            for acc in read_only_accounts:
                cluster["awsInfrastructureManagementAccounts"].append(  # type: ignore # noqa: E501
                    {
                        "account": {
                            "name": acc,
                            "uid": acc,
                            "terraformUsername": "terraform",
                            "automationToken": {},
                        },
                        "accessLevel": "read-only",
                        "default": None,
                    }
                )
        if network_mgmt_accounts:
            for idx, acc in enumerate(network_mgmt_accounts):
                cluster["awsInfrastructureManagementAccounts"].append(  # type: ignore # noqa: E501
                    {
                        "account": {
                            "name": acc,
                            "uid": acc,
                            "terraformUsername": "terraform",
                            "automationToken": {},
                        },
                        "accessLevel": "network-mgmt",
                        "default": True if idx == 0 else None,
                    }
                )
    return cluster


def build_requester_connection(
    name: str, peer_cluster: dict[str, Any], manage_routes: bool = True
):
    return {
        "name": name,
        "provider": "cluster-vpc-requester",
        "manageRoutes": manage_routes,
        "cluster": peer_cluster,
    }


def build_accepter_connection(
    name: str,
    cluster: str,
    aws_infra_acc: Optional[str] = None,
    manage_routes: bool = True,
):
    connection = {
        "name": name,
        "provider": "cluster-vpc-accepter",
        "manageRoutes": manage_routes,
        "cluster": {"name": cluster},
        "awsInfrastructureManagementAccount": None,
    }
    if aws_infra_acc:
        connection["awsInfrastructureManagementAccount"] = {
            "name": aws_infra_acc,
            "uid": aws_infra_acc,
            "terraformUsername": "terraform",
            "automationToken": {},
        }
    return connection


def test_c2c_vpc_peering_assume_role_accepter_connection_acc_overwrite(mocker):
    """
    makes sure the peer connection account overwrite on the accepter is used
    when available. in this test, the overwrite is also allowed
    """
    requester_cluster = build_cluster(name="r_c")
    accepter_cluster = build_cluster(
        name="a_c", network_mgmt_accounts=["acc", "acc_overwrite"]
    )
    accepter_connection = build_accepter_connection(
        name="a_c", cluster="a_c", aws_infra_acc="acc_overwrite"
    )

    ocm = (
        MockOCM()
        .register("r_c", "acc_overwrite", "terraform", "arn:r_acc_overwrite")
        .register("r_c", "acc", "terraform", "arn:r_acc")
        .register("a_c", "acc_overwrite", "terraform", "arn:a_acc_overwrite")
        .register("a_c", "acc", "terraform", "arn:a_acc")
        .auto_speced_mock(mocker)
    )
    req_aws, acc_aws = integ.aws_assume_roles_for_cluster_vpc_peering(
        requester_cluster, accepter_connection, accepter_cluster, ocm
    )

    expected_req_aws = {
        "name": "acc_overwrite",
        "uid": "acc_overwrite",
        "terraformUsername": "terraform",
        "automationToken": {},
        "assume_role": "arn:r_acc_overwrite",
        "assume_region": "region",
        "assume_cidr": "r_c",
    }
    assert req_aws == expected_req_aws

    expected_acc_aws = {
        "name": "acc_overwrite",
        "uid": "acc_overwrite",
        "terraformUsername": "terraform",
        "automationToken": {},
        "assume_role": "arn:a_acc_overwrite",
        "assume_region": "region",
        "assume_cidr": "a_c",
    }
    assert acc_aws == expected_acc_aws


def test_c2c_vpc_peering_assume_role_acc_overwrite_fail(mocker):
    """
    try overwrite the account to be used on the accepter connection with an
    account not listed on the accepter cluster
    """
    requester_cluster = build_cluster(name="r_c")
    accepter_cluster = build_cluster(name="a_c", network_mgmt_accounts=["acc"])
    accepter_connection = build_accepter_connection(
        name="a_c", cluster="a_c", aws_infra_acc="acc_overwrite"
    )

    ocm = (
        MockOCM()
        .register("r_c", "acc", "terraform", "arn:r_acc")
        .register("a_c", "acc", "terraform", "arn:a_acc")
        .auto_speced_mock(mocker)
    )
    with pytest.raises(BadTerraformPeeringState) as ex:
        integ.aws_assume_roles_for_cluster_vpc_peering(
            requester_cluster, accepter_connection, accepter_cluster, ocm
        )
    assert str(ex.value).startswith("[account_not_allowed]")


def test_c2c_vpc_peering_assume_role_accepter_cluster_account(mocker):
    """
    makes sure the clusters default infra account is used when no peer
    connection overwrite exists
    """
    requester_cluster = build_cluster(name="r_c")
    accepter_cluster = build_cluster(
        name="a_c", network_mgmt_accounts=["default_acc", "other_acc"]
    )
    accepter_connection = build_accepter_connection(name="a_c", cluster="a_c")

    ocm = (
        MockOCM()
        .register("r_c", "default_acc", "terraform", "arn:r_default_acc")
        .register("r_c", "other_acc", "terraform", "arn:r_other_acc")
        .register("a_c", "default_acc", "terraform", "arn:a_default_acc")
        .register("a_c", "other_acc", "terraform", "arn:a_other_acc")
        .auto_speced_mock(mocker)
    )
    req_aws, acc_aws = integ.aws_assume_roles_for_cluster_vpc_peering(
        requester_cluster, accepter_connection, accepter_cluster, ocm
    )

    expected_req_aws = {
        "name": "default_acc",
        "uid": "default_acc",
        "terraformUsername": "terraform",
        "automationToken": {},
        "assume_role": "arn:r_default_acc",
        "assume_region": "region",
        "assume_cidr": "r_c",
    }
    assert req_aws == expected_req_aws

    expected_acc_aws = {
        "name": "default_acc",
        "uid": "default_acc",
        "terraformUsername": "terraform",
        "automationToken": {},
        "assume_role": "arn:a_default_acc",
        "assume_region": "region",
        "assume_cidr": "a_c",
    }
    assert acc_aws == expected_acc_aws


def test_c2c_vpc_peering_missing_ocm_assume_role(mocker):
    """
    makes sure the clusters infra account is used when no peer connection
    overwrite exists
    """
    requester_cluster = build_cluster(name="r_c")
    accepter_cluster = build_cluster(name="a_c", network_mgmt_accounts=["acc"])
    accepter_connection = build_accepter_connection(name="a_c", cluster="a_c")

    ocm = MockOCM().auto_speced_mock(mocker)

    with pytest.raises(BadTerraformPeeringState) as ex:
        integ.aws_assume_roles_for_cluster_vpc_peering(
            requester_cluster, accepter_connection, accepter_cluster, ocm
        )
    assert str(ex.value).startswith("[assume_role_not_found]")


def test_c2c_vpc_peering_missing_account(mocker):
    """
    test the fallback logic, looking for network-mgmt groups accounts
    """
    requester_cluster = build_cluster(name="r_c")
    accepter_cluster = build_cluster(name="a_c")
    accepter_connection = build_accepter_connection(name="a_c", cluster="a_c")

    ocm = MockOCM().auto_speced_mock(mocker)

    with pytest.raises(BadTerraformPeeringState) as ex:
        integ.aws_assume_roles_for_cluster_vpc_peering(
            requester_cluster, accepter_connection, accepter_cluster, ocm
        )
    assert str(ex.value).startswith("[no_account_available]")


class TestRun(testslide.TestCase):
    def setUp(self):
        super().setUp()

        self.awsapi = testslide.StrictMock(aws_api.AWSApi)
        self.mock_constructor(aws_api, "AWSApi").to_return_value(self.awsapi)

        self.build_desired_state_vpc = self.mock_callable(
            integ, "build_desired_state_vpc"
        )
        self.build_desired_state_all_clusters = self.mock_callable(
            integ, "build_desired_state_all_clusters"
        )
        self.build_desired_state_vpc_mesh = self.mock_callable(
            integ, "build_desired_state_vpc_mesh"
        )
        self.terraform = testslide.StrictMock(terraform.TerraformClient)
        self.terrascript = testslide.StrictMock(terrascript.TerrascriptClient)
        self.mock_constructor(terraform, "TerraformClient").to_return_value(
            self.terraform
        )
        self.mock_constructor(terrascript, "TerrascriptClient").to_return_value(
            self.terrascript
        )
        self.ocmmap = testslide.StrictMock(ocm.OCMMap)
        self.mock_constructor(ocm, "OCMMap").to_return_value(self.ocmmap)
        self.mock_callable(queries, "get_aws_accounts").to_return_value(
            [{"name": "desired_requester_account"}]
        )
        self.clusters = (
            self.mock_callable(queries, "get_clusters")
            .to_return_value(
                [{"name": "aname", "ocm": "aocm", "peering": {"apeering"}}]
            )
            .and_assert_called_once()
        )
        self.settings = (
            self.mock_callable(queries, "get_app_interface_settings")
            .to_return_value({})
            .and_assert_called_once()
        )

        self.mock_callable(self.terrascript, "populate_vpc_peerings").to_return_value(
            None
        ).and_assert_called_once()
        self.mock_callable(self.terrascript, "dump").to_return_value(
            {"some_account": "/some/dir"}
        ).and_assert_called_once()
        # Sigh...
        self.exit = self.mock_callable(sys, "exit").to_raise(OSError("Exit called!"))
        self.addCleanup(testslide.mock_callable.unpatch_all_callable_mocks)

    def initialize_desired_states(self, error_code):
        self.build_desired_state_vpc.to_return_value(
            (
                [
                    {
                        "connection_name": "desired_vpc_conn",
                        "requester": {"account": {"name": "desired_requester_account"}},
                        "accepter": {"account": {"name": "desired_accepter_account"}},
                    },
                ],
                error_code,
            )
        )
        self.build_desired_state_all_clusters.to_return_value(
            (
                [
                    {
                        "connection_name": "all_clusters_vpc_conn",
                        "requester": {
                            "account": {"name": "all_clusters_requester_account"}
                        },
                        "accepter": {
                            "account": {
                                "name": "all_clusters_accepter_account",
                            }
                        },
                    }
                ],
                error_code,
            )
        )
        self.build_desired_state_vpc_mesh.to_return_value(
            (
                [
                    {
                        "connection_name": "mesh_vpc_conn",
                        "requester": {
                            "account": {"name": "mesh_requester_account"},
                        },
                        "accepter": {
                            "account": {"name": "mesh_accepter_account"},
                        },
                    }
                ],
                error_code,
            )
        )

        self.mock_callable(self.terrascript, "populate_additional_providers").for_call(
            [
                {"name": "desired_requester_account"},
                {"name": "mesh_requester_account"},
                {"name": "all_clusters_requester_account"},
                {"name": "desired_accepter_account"},
                {"name": "mesh_accepter_account"},
                {"name": "all_clusters_accepter_account"},
            ]
        ).to_return_value(None).and_assert_called_once()

    def test_all_fine(self):
        self.initialize_desired_states(False)
        self.mock_callable(self.terraform, "plan").to_return_value(
            (False, False)
        ).and_assert_called_once()
        self.mock_callable(self.terraform, "cleanup").to_return_value(
            None
        ).and_assert_called_once()
        self.mock_callable(self.terraform, "apply").to_return_value(
            None
        ).and_assert_called_once()
        self.exit.for_call(0).and_assert_called_once()
        with self.assertRaises(OSError):
            integ.run(False, print_to_file=None, enable_deletion=False)

    def test_fail_state(self):
        """Ensure we don't change the world if there are failures"""
        self.initialize_desired_states(True)
        self.mock_callable(self.terraform, "plan").to_return_value(
            (False, False)
        ).and_assert_not_called()
        self.mock_callable(self.terraform, "cleanup").to_return_value(
            None
        ).and_assert_not_called()
        self.mock_callable(self.terraform, "apply").to_return_value(
            None
        ).and_assert_not_called()
        self.exit.for_call(1).and_assert_called_once()
        with self.assertRaises(OSError):
            integ.run(False, print_to_file=None, enable_deletion=True)

    def test_dry_run(self):
        self.initialize_desired_states(False)

        self.mock_callable(self.terraform, "plan").to_return_value(
            (False, False)
        ).and_assert_called_once()
        self.mock_callable(self.terraform, "cleanup").to_return_value(
            None
        ).and_assert_called_once()
        self.mock_callable(self.terraform, "apply").to_return_value(
            None
        ).and_assert_not_called()
        self.exit.for_call(0).and_assert_called_once()
        with self.assertRaises(OSError):
            integ.run(True, print_to_file=None, enable_deletion=False)

    def test_dry_run_with_failures(self):
        """This is what we do during PR checks and new clusters!"""
        self.initialize_desired_states(True)
        self.mock_callable(self.terraform, "plan").to_return_value(
            (False, False)
        ).and_assert_not_called()
        self.mock_callable(self.terraform, "apply").to_return_value(
            None
        ).and_assert_not_called()
        self.exit.for_call(1).and_assert_called_once()
        with self.assertRaises(OSError):
            integ.run(True, print_to_file=None, enable_deletion=False)

    def test_dry_run_print_only_with_failures(self):
        """This is what we do during PR checks and new clusters!"""
        self.initialize_desired_states(True)
        self.mock_callable(self.terraform, "plan").to_return_value(
            (False, False)
        ).and_assert_not_called()
        self.mock_callable(self.terraform, "apply").to_return_value(
            None
        ).and_assert_not_called()
        self.exit.for_call(0).and_assert_called_once()
        with self.assertRaises(OSError):
            integ.run(True, print_to_file="some/dir", enable_deletion=False)
