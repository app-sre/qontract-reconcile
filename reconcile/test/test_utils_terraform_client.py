import base64
from unittest.mock import create_autospec
import pytest

from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
    ExternalResourceUniqueKey,
)
import reconcile.utils.terraform_client as tfclient
from reconcile.utils.aws_api import AWSApi


@pytest.fixture
def aws_api():
    return create_autospec(AWSApi)


def test_no_deletion_approvals(aws_api):
    account = {"name": "a1", "deletionApprovals": []}
    tf = tfclient.TerraformClient("integ", "v1", "integ_pfx", [account], {}, 1, aws_api)
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
