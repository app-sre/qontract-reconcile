import base64
import tempfile
from collections.abc import Callable
from logging import DEBUG
from operator import itemgetter
from unittest.mock import (
    MagicMock,
    create_autospec,
)

import pytest
from botocore.errorfactory import ClientError
from pytest_mock import MockerFixture
from python_terraform import (
    IsFlagged,
    Terraform,
)

import reconcile.utils.terraform_client as tfclient
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
    ExternalResourceUniqueKey,
)


@pytest.fixture
def aws_api():
    return create_autospec(AWSApi)


ACCOUNT_NAME = "a1"


@pytest.fixture
def tf(aws_api):
    account = {"name": ACCOUNT_NAME, "deletionApprovals": []}
    return tfclient.TerraformClient(
        "integ", "v1", "integ_pfx", [account], {}, 1, aws_api
    )


def test_no_deletion_approvals(tf):
    result = tf.deletion_approved("a1", "t1", "n1")
    assert result is False


def test_deletion_not_approved(aws_api):
    account = {
        "name": "a1",
        "deletionApprovals": [{"type": "t1", "name": "n1", "expiration": "2000-01-01"}],
    }
    tf = tfclient.TerraformClient("integ", "v1", "integ_pfx", [account], {}, 1, aws_api)
    result = tf.deletion_approved("a1", "t2", "n2")
    assert result is False


def test_deletion_approved_expired(aws_api):
    account = {
        "name": "a1",
        "deletionApprovals": [{"type": "t1", "name": "n1", "expiration": "2000-01-01"}],
    }
    tf = tfclient.TerraformClient("integ", "v1", "integ_pfx", [account], {}, 1, aws_api)
    result = tf.deletion_approved("a1", "t1", "n1")
    assert result is False


def test_deletion_approved(aws_api):
    account = {
        "name": "a1",
        "deletionApprovals": [{"type": "t1", "name": "n1", "expiration": "2500-01-01"}],
    }
    tf = tfclient.TerraformClient("integ", "v1", "integ_pfx", [account], {}, 1, aws_api)
    result = tf.deletion_approved("a1", "t1", "n1")
    assert result is True


def test_expiration_value_error(aws_api):
    account = {
        "name": "a1",
        "deletionApprovals": [{"type": "t1", "name": "n1", "expiration": "2000"}],
    }
    tf = tfclient.TerraformClient("integ", "v1", "integ_pfx", [account], {}, 1, aws_api)
    with pytest.raises(tfclient.DeletionApprovalExpirationValueError):
        tf.deletion_approved("a1", "t1", "n1")


def test_get_replicas_info_via_replica_source():
    resource_specs = [
        ExternalResourceSpec(
            provision_provider="aws",
            provisioner={"name": "acc"},
            resource={
                "identifier": "replica-id",
                "provider": "rds",
                "defaults": "defaults-ref",
                "replica_source": "replica-source-id",
            },
            namespace={},
        )
    ]
    result = tfclient.TerraformClient.get_replicas_info(resource_specs)
    expected = {"acc": {"replica-id-rds": "replica-source-id-rds"}}
    assert result == expected


def test_build_oc_secret():
    integration = "integ"
    integration_version = "v1"
    account = "account"

    spec = ExternalResourceSpec(
        provision_provider="aws",
        provisioner={"name": account},
        resource={
            "identifier": "replica-id",
            "provider": "rds",
            "output_resource_name": "name",
            "defaults": "defaults-ref",
            "overrides": '{"replicate_source_db": "replica-source-id-from-override"}',
            "annotations": '{"annotation1": "value1", "annotation2": "value2"}',
        },
        namespace={},
    )
    spec.secret = {
        "data1": "value",
        "data2": "",
    }

    expected_annotations = {
        "annotation1": "value1",
        "annotation2": "value2",
        "qontract.recycle": "true",
    }

    resource = spec.build_oc_secret(integration, integration_version)

    # check metadata
    assert resource.caller == account
    assert resource.kind == "Secret"
    assert resource.name == "name"
    assert resource.integration == integration
    assert resource.integration_version == integration_version
    assert resource.body["metadata"]["annotations"] == expected_annotations

    # check data
    assert len(resource.body["data"]) == 2
    assert "data1" in resource.body["data"]
    assert base64.b64decode(resource.body["data"]["data1"]).decode("utf8") == "value"

    assert "data2" in resource.body["data"]
    assert not resource.body["data"]["data2"]


def test_populate_terraform_output_secret():
    integration_prefix = "integ_pfx"
    account = "account"
    resource_specs = [
        ExternalResourceSpec(
            provision_provider="aws",
            provisioner={"name": account},
            resource={
                "identifier": "id",
                "provider": "provider",
            },
            namespace={},
        )
    ]
    existing_secrets = {
        account: {
            "id-provider": {
                "key": "value",
                f"{integration_prefix}_some_metadata_field": "metadata",
            }
        }
    }

    tfclient.TerraformClient._populate_terraform_output_secrets(
        {ExternalResourceUniqueKey.from_spec(s): s for s in resource_specs},
        existing_secrets,
        integration_prefix,
        {},
    )

    assert resource_specs[0].secret
    assert len(resource_specs[0].secret) == 1
    assert resource_specs[0].get_secret_field("key") == "value"


def test_populate_terraform_output_secret_with_replica_credentials():
    integration_prefix = "integ_pfx"
    account = "account"
    replica = ExternalResourceSpec(
        provision_provider="aws",
        provisioner={"name": account},
        resource={
            "identifier": "replica-db",
            "provider": "rds",
        },
        namespace={},
    )
    replica_source = ExternalResourceSpec(
        provision_provider="aws",
        provisioner={"name": account},
        resource={
            "identifier": "main-db",
            "provider": "rds",
        },
        namespace={},
    )

    resource_specs = {
        replica_source.id_object(): replica_source,
        replica.id_object(): replica,
    }

    replica_source_info = {
        account: {replica.output_prefix: replica_source.output_prefix}
    }

    existing_secrets = {
        account: {
            "replica-db-rds": {"key": "value"},
            "main-db-rds": {"db.user": "user", "db.password": "password"},
        }
    }

    tfclient.TerraformClient._populate_terraform_output_secrets(
        resource_specs, existing_secrets, integration_prefix, replica_source_info
    )

    assert replica.secret
    assert replica.get_secret_field("key") == "value"
    assert replica.get_secret_field("db.user") == "user"
    assert replica.get_secret_field("db.password") == "password"


def test__resource_diff_changed_fields(tf):
    changed = tf._resource_diff_changed_fields(
        "update",
        {
            "before": {"a": 1, "c": None},
            "after": {"a": 2, "b": "foo", "c": 1},
        },
    )

    assert changed == {"a", "b", "c"}

    changed = tf._resource_diff_changed_fields(
        "update",
        {"after": {"field": 1}},
    )

    assert changed == {"field"}

    changed = tf._resource_diff_changed_fields(
        "update",
        {"before": {"field": 1}},
    )

    assert changed == {"field"}

    changed = tf._resource_diff_changed_fields(
        "create",
        {"before": {"field": 1}},
    )

    assert changed == set()


@pytest.mark.parametrize(
    "before,after,response,expected",
    [
        pytest.param(
            {},
            {},
            {},
            False,
            id="should return false with no data",
        ),
        pytest.param(
            {
                "availability_zone": "us-east-1a",
                "allocated_storage": "100",
            },
            {
                "availability_zone": "us-east-1a",
                "allocated_storage": "100",
            },
            {},
            False,
            id="should return false with identical before and after",
        ),
        pytest.param(
            {
                "availability_zone": "us-east-1a",
                "allocated_storage": 100,
            },
            {
                "availability_zone": "us-east-1a",
                "allocated_storage": 200,
            },
            {"DBInstances": [{}]},
            False,
            id="should return false with no database instance",
        ),
        pytest.param(
            {
                "availability_zone": "us-east-1a",
                "allocated_storage": 100,
            },
            {
                "availability_zone": "us-east-1a",
                "allocated_storage": 200,
            },
            {"DBInstances": [{"PendingModifiedValues": {}}]},
            False,
            id="should return false for database instance without pending changes",
        ),
        pytest.param(
            {
                "availability_zone": "us-east-1a",
                "apply_immediately": True,
            },
            {
                "availability_zone": "us-east-1a",
                "apply_immediately": False,
            },
            {
                "DBInstances": [
                    {
                        "PendingModifiedValues": {
                            "AllocatedStorage": 200,
                        }
                    }
                ]
            },
            False,
            id="should return false with data that does not match",
        ),
        pytest.param(
            {
                "availability_zone": "us-east-1a",
                "allocated_storage": 100,
            },
            {
                "availability_zone": "us-east-1a",
                "allocated_storage": 200,
            },
            {
                "DBInstances": [
                    {
                        "PendingModifiedValues": {
                            "AllocatedStorage": 100,
                        }
                    }
                ]
            },
            False,
            id="should return false with data that is old",
        ),
        pytest.param(
            {
                "availability_zone": "us-east-1a",
                "apply_immediately": False,
                "allocated_storage": 100,
            },
            {
                "availability_zone": "us-east-1a",
                "apply_immediately": True,
                "allocated_storage": 200,
            },
            {
                "DBInstances": [
                    {
                        "PendingModifiedValues": {
                            "AllocatedStorage": 200,
                        }
                    }
                ]
            },
            False,
            id="should return false with attribute that is not allowed",
        ),
        pytest.param(
            {
                "availability_zone": "us-east-1a",
                "allocated_storage": 100,
                "engine_version": "11.13",
            },
            {
                "availability_zone": "us-east-1a",
                "allocated_storage": 200,
                "engine_version": "11.14",
            },
            {
                "DBInstances": [
                    {
                        "PendingModifiedValues": {
                            "AllocatedStorage": 200,
                            "EngineVersion": "11.14",
                        }
                    }
                ]
            },
            True,
            id="should return true with valid data that matches",
        ),
    ],
)
def test__can_skip_rds_modifications(aws_api, tf, before, after, response, expected):
    aws_api.describe_rds_db_instance.return_value = response

    actual = tf._can_skip_rds_modifications(
        account_name="a1",
        resource_name="test-database-1",
        resource_change={"before": before, "after": after},
    )

    assert actual == expected


def test__can_skip_rds_modifications_with_client_error(aws_api, tf, caplog):
    aws_api.describe_rds_db_instance.side_effect = ClientError(
        {
            "Error": {
                "Code": "DBInstanceNotFound",
                "Message": "DBInstance test-database-1 not found.",
            }
        },
        "DescribeDBInstances",
    )

    caplog.set_level(DEBUG)

    actual = tf._can_skip_rds_modifications(
        account_name="a1",
        resource_name="test-database-1",
        resource_change={
            "before": {
                "availability_zone": "us-east-1a",
                "allocated_storage": "100",
            },
            "after": {
                "availability_zone": "us-east-1a",
                "allocated_storage": "200",
            },
        },
    )

    assert not actual
    assert [itemgetter(1, 2)(v) for v in caplog.record_tuples] == [
        (DEBUG, "Resource test-database-1 changes in Terraform: ['allocated_storage']"),
        (DEBUG, "Resource does not exist: test-database-1"),
    ]


def test__can_skip_rds_modifications_with_exception(aws_api, tf):
    with pytest.raises(Exception) as error:
        aws_api.describe_rds_db_instance.side_effect = Exception("a-test-exception")

        tf._can_skip_rds_modifications(
            account_name="a1",
            resource_name="test-database-1",
            resource_change={
                "before": {
                    "availability_zone": "us-east-1a",
                    "allocated_storage": "100",
                },
                "after": {
                    "availability_zone": "us-east-1a",
                    "allocated_storage": "200",
                },
            },
        )

    assert "a-test-exception" in str(error.value)


def test_validate_db_upgrade_no_upgrade(aws_api, tf):
    aws_api.get_db_valid_upgrade_target.return_value = [
        {"Engine": "postgres", "EngineVersion": "11.17", "IsMajorVersionUpgrade": False}
    ]

    tf.validate_db_upgrade(
        account_name="a1",
        resource_name="test-database-1",
        resource_change={
            "before": {
                "engine": "postgres",
                "engine_version": "11.12",
            },
            "after": {
                "engine": "postgres",
                "engine_version": "11.12",
            },
        },
    )


def test_validate_db_upgrade(aws_api, tf):
    aws_api.get_db_valid_upgrade_target.return_value = [
        {"Engine": "postgres", "EngineVersion": "11.17", "IsMajorVersionUpgrade": False}
    ]

    tf.validate_db_upgrade(
        account_name="a1",
        resource_name="test-database-1",
        resource_change={
            "before": {
                "engine": "postgres",
                "engine_version": "11.12",
                "availability_zone": "us-east-1a",
            },
            "after": {
                "engine": "postgres",
                "engine_version": "11.17",
            },
        },
    )


def test_validate_db_upgrade_major_version_upgrade(aws_api, tf):
    aws_api.get_db_valid_upgrade_target.return_value = [
        {"Engine": "postgres", "EngineVersion": "13.3", "IsMajorVersionUpgrade": True}
    ]

    tf.validate_db_upgrade(
        account_name="a1",
        resource_name="test-database-1",
        resource_change={
            "before": {
                "engine": "postgres",
                "engine_version": "11.12",
                "availability_zone": "us-east-1a",
            },
            "after": {
                "engine": "postgres",
                "engine_version": "13.3",
                "allow_major_version_upgrade": True,
            },
        },
    )


def test_validate_db_upgrade_cannot_upgrade(aws_api, tf):
    aws_api.get_db_valid_upgrade_target.return_value = [
        {"Engine": "postgres", "EngineVersion": "13.3", "IsMajorVersionUpgrade": True}
    ]

    with pytest.raises(ValueError) as error:
        tf.validate_db_upgrade(
            account_name="a1",
            resource_name="test-database-1",
            resource_change={
                "before": {
                    "engine": "postgres",
                    "engine_version": "11.12",
                    "availability_zone": "us-east-1a",
                },
                "after": {
                    "engine": "postgres",
                    "engine_version": "14.2",
                },
            },
        )

    assert "Cannot upgrade RDS instance: test-database-1 from 11.12 to 14.2" == str(
        error.value
    )


def test_validate_db_upgrade_major_version_upgrade_not_allow(aws_api, tf):
    aws_api.get_db_valid_upgrade_target.return_value = [
        {"Engine": "postgres", "EngineVersion": "13.3", "IsMajorVersionUpgrade": True}
    ]

    with pytest.raises(ValueError) as error:
        tf.validate_db_upgrade(
            account_name="a1",
            resource_name="test-database-1",
            resource_change={
                "before": {
                    "engine": "postgres",
                    "engine_version": "11.12",
                    "availability_zone": "us-east-1a",
                },
                "after": {
                    "engine": "postgres",
                    "engine_version": "13.3",
                },
            },
        )

    assert (
        "allow_major_version_upgrade is not enabled for upgrading RDS instance: test-database-1 to a new major version."
        == str(error.value)
    )


def test_validate_db_upgrade_with_empty_valid_upgrade_targe_and_allow_major_version_upgrade(
    aws_api: AWSApi,
    tf: tfclient.TerraformClient,
) -> None:
    aws_api.get_db_valid_upgrade_target.return_value = []  # type: ignore[attr-defined]

    tf.validate_db_upgrade(
        account_name="a1",
        resource_name="test-database-1",
        resource_change={
            "before": {
                "engine": "postgres",
                "engine_version": "11.12",
                "availability_zone": "us-east-1a",
            },
            "after": {
                "engine": "postgres",
                "engine_version": "11.17",
                "allow_major_version_upgrade": True,
            },
        },
    )


def test_validate_db_upgrade_with_empty_valid_upgrade_targe_and_not_allow_major_version_upgrade(
    aws_api: AWSApi,
    tf: tfclient.TerraformClient,
) -> None:
    aws_api.get_db_valid_upgrade_target.return_value = []  # type: ignore[attr-defined]

    with pytest.raises(ValueError) as error:
        tf.validate_db_upgrade(
            account_name="a1",
            resource_name="test-database-1",
            resource_change={
                "before": {
                    "engine": "postgres",
                    "engine_version": "11.12",
                    "availability_zone": "us-east-1a",
                },
                "after": {
                    "engine": "postgres",
                    "engine_version": "11.17",
                },
            },
        )

    assert (
        "allow_major_version_upgrade is not enabled for upgrading RDS instance: "
        "test-database-1 to a new version when there is no valid upgrade target available."
        == str(error.value)
    )


def test_check_output_debug(
    tf: tfclient.TerraformClient,
    mocker: MockerFixture,
) -> None:
    mocked_logging = mocker.patch("reconcile.utils.terraform_client.logging")

    result = tf.check_output("name", "cmd", 0, "out", "", "")

    assert result is False
    mocked_logging.debug.assert_called_once_with("[name - cmd] out")
    mocked_logging.warning.assert_not_called()
    mocked_logging.error.assert_not_called()


def test_check_output_warning(
    tf: tfclient.TerraformClient,
    mocker: MockerFixture,
) -> None:
    mocked_logging = mocker.patch("reconcile.utils.terraform_client.logging")

    result = tf.check_output("name", "cmd", 0, "out", "error", "")

    assert result is False
    mocked_logging.debug.assert_called_once_with("[name - cmd] out")
    mocked_logging.warning.assert_called_once_with("[name - cmd] error")
    mocked_logging.error.assert_not_called()


def test_check_output_from_terraform_log(
    tf: tfclient.TerraformClient,
    mocker: MockerFixture,
) -> None:
    mocked_logging = mocker.patch("reconcile.utils.terraform_client.logging")

    log = "2023-07-20T15:49:09.681+1000 [INFO] doing something"

    result = tf.check_output("name", "cmd", 0, "", "", log)

    assert result is False
    mocked_logging.debug.assert_not_called()
    mocked_logging.warning.assert_not_called()
    mocked_logging.error.assert_not_called()


def test_check_output_warning_from_provider_warn_log(
    tf: tfclient.TerraformClient,
    mocker: MockerFixture,
) -> None:
    mocked_logging = mocker.patch("reconcile.utils.terraform_client.logging")

    log = (
        "2023-07-20T15:49:09.681+1000 [INFO]  plugin.terraform-provider-aws_v3.76.0_x5: 2023/07/20 15:49:09 "
        "[WARN] DB Instance (xxx) not found, removing from state: timestamp=2023-07-20T15:49:09.673+1000"
    )

    result = tf.check_output("name", "cmd", 0, "", "", log)

    assert result is False
    mocked_logging.debug.assert_not_called()
    mocked_logging.warning.assert_called_once_with(f"[name - cmd] {log}")
    mocked_logging.error.assert_not_called()


def test_check_output_error_from_provider_error_log(
    tf: tfclient.TerraformClient,
    mocker: MockerFixture,
) -> None:
    mocked_logging = mocker.patch("reconcile.utils.terraform_client.logging")

    log = (
        "2023-07-20T15:49:09.681+1000 [INFO]  plugin.terraform-provider-aws_v3.76.0_x5: 2023/07/20 15:49:09 "
        "[ERROR] something is wrong: timestamp=2023-07-20T15:49:09.673+1000"
    )

    result = tf.check_output("name", "cmd", 0, "", "", log)

    assert result is False
    mocked_logging.debug.assert_not_called()
    mocked_logging.warning.assert_called_once_with(f"[name - cmd] {log}")
    mocked_logging.error.assert_not_called()


def test_check_output_error(
    tf: tfclient.TerraformClient,
    mocker: MockerFixture,
) -> None:
    mocked_logging = mocker.patch("reconcile.utils.terraform_client.logging")

    result = tf.check_output("name", "cmd", 1, "", "error", "")

    assert result is True
    mocked_logging.debug.assert_not_called()
    mocked_logging.warning.assert_not_called()
    mocked_logging.error.assert_called_once_with("[name - cmd] error")


@pytest.fixture
def init_spec_builder() -> Callable[..., dict]:
    def builder(name: str, working_dir: str) -> dict:
        return {
            "name": name,
            "wd": working_dir,
        }

    return builder


def test_terraform_init(
    tf: tfclient.TerraformClient,
    mocker: MockerFixture,
    init_spec_builder: Callable[..., dict],
) -> None:
    mocked_tf = mocker.patch("reconcile.utils.terraform_client.Terraform")
    mocked_tf.return_value.init.return_value = (0, "", "")
    mocked_tempfile = mocker.patch("reconcile.utils.terraform_client.tempfile")
    mocked_logging = mocker.patch("reconcile.utils.terraform_client.logging")
    warning_log = "[INFO] a [WARN]"
    with mocked_tempfile.NamedTemporaryFile.return_value as f:
        f.name = "temp-name"
        f.read.return_value.decode.return_value = warning_log

    with tempfile.TemporaryDirectory() as working_dir:
        init_spec = init_spec_builder(ACCOUNT_NAME, working_dir)

        tf.terraform_init(init_spec)

    mocked_tf.assert_called_once_with(
        working_dir=working_dir, is_env_vars_included=True
    )
    mocked_tf.return_value.init.assert_called_once_with()
    mocked_logging.warning.assert_called_once_with(
        f"[{ACCOUNT_NAME} - init] {warning_log}"
    )


@pytest.fixture
def terraform_spec_builder() -> Callable[..., dict]:
    def builder(name: str, working_dir: str) -> dict:
        return {
            "name": name,
            "tf": create_autospec(Terraform, working_dir=working_dir),
        }

    return builder


def test_terraform_output(
    tf: tfclient.TerraformClient,
    mocker: MockerFixture,
    terraform_spec_builder: Callable[..., dict],
) -> None:
    mocked_tempfile = mocker.patch("reconcile.utils.terraform_client.tempfile")
    mocked_logging = mocker.patch("reconcile.utils.terraform_client.logging")
    warning_log = "[INFO] a [WARN]"
    with mocked_tempfile.NamedTemporaryFile.return_value as f:
        f.name = "temp-name"
        f.read.return_value.decode.return_value = warning_log

    with tempfile.TemporaryDirectory() as working_dir:
        spec = terraform_spec_builder(ACCOUNT_NAME, working_dir)
        spec["tf"].output_cmd = MagicMock(return_value=(0, "{}", ""))

        name, output = tf.terraform_output(spec)

    assert name == ACCOUNT_NAME
    assert output == {}
    spec["tf"].output_cmd.assert_called_once_with(json=IsFlagged)
    mocked_logging.warning.assert_called_once_with(
        f"[{ACCOUNT_NAME} - output] {warning_log}"
    )


def test_terraform_plan(
    tf: tfclient.TerraformClient,
    mocker: MockerFixture,
    terraform_spec_builder,
) -> None:
    mocked_lean_tf = mocker.patch("reconcile.utils.terraform_client.lean_tf")
    mocked_lean_tf.show_json.return_value = {"format_version": "0.1"}
    mocked_tempfile = mocker.patch("reconcile.utils.terraform_client.tempfile")
    mocked_logging = mocker.patch("reconcile.utils.terraform_client.logging")
    warning_log = "[INFO] a [WARN]"
    with mocked_tempfile.NamedTemporaryFile.return_value as f:
        f.name = "temp-name"
        f.read.return_value.decode.return_value = warning_log

    with tempfile.TemporaryDirectory() as working_dir:
        spec = terraform_spec_builder(ACCOUNT_NAME, working_dir)
        spec["tf"].plan.return_value = (0, "", "")

        disabled_deletion_detected, created_users, error = tf.terraform_plan(
            spec,
            False,
        )

    assert disabled_deletion_detected is False
    assert created_users == []
    assert error is False
    spec["tf"].plan.assert_called_once_with(
        detailed_exitcode=False, parallelism=tf.parallelism, out=ACCOUNT_NAME
    )
    mocked_logging.warning.assert_called_once_with(
        f"[{ACCOUNT_NAME} - plan] {warning_log}"
    )


def test_terraform_apply(
    tf: tfclient.TerraformClient,
    mocker: MockerFixture,
    terraform_spec_builder,
) -> None:
    mocked_tempfile = mocker.patch("reconcile.utils.terraform_client.tempfile")
    mocked_logging = mocker.patch("reconcile.utils.terraform_client.logging")
    warning_log = "[INFO] a [WARN]"
    with mocked_tempfile.NamedTemporaryFile.return_value as f:
        f.name = "temp-name"
        f.read.return_value.decode.return_value = warning_log

    with tempfile.TemporaryDirectory() as working_dir:
        spec = terraform_spec_builder(ACCOUNT_NAME, working_dir)
        spec["tf"].apply.return_value = (0, "", "")

        error = tf.terraform_apply(spec)

    assert error is False
    spec["tf"].apply.assert_called_once_with(dir_or_plan=ACCOUNT_NAME, var=None)
    mocked_logging.warning.assert_called_once_with(
        f"[{ACCOUNT_NAME} - apply] {warning_log}"
    )
