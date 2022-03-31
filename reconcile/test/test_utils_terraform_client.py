from unittest.mock import create_autospec

import pytest

import reconcile.utils.terraform_client as tfclient
from reconcile.utils.aws_api import AWSApi
from reconcile.utils import gql


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
    namespace = {
        "terraformResources": [
            {
                "account": "acc",
                "identifier": "replica-id",
                "provider": "rds",
                "defaults": "defaults-ref",
                "replica_source": "replica-source-id",
            }
        ]
    }
    result = tfclient.TerraformClient.get_replicas_info([namespace])
    expected = {"acc": {"replica-id-rds": "replica-source-id-rds"}}
    assert result == expected


def test_get_replicas_info_via_replica_source_overrides_present():
    # this test shows that the direct replica_source on the tf resource
    # has precendence over overrides
    namespace = {
        "terraformResources": [
            {
                "account": "acc",
                "identifier": "replica-id",
                "provider": "rds",
                "defaults": "defaults-ref",
                "replica_source": "replica-source-id",
                "overrides": '{"replicate_source_db": "replica-source-id-from-override"}',
            }
        ]
    }
    result = tfclient.TerraformClient.get_replicas_info([namespace])
    expected = {"acc": {"replica-id-rds": "replica-source-id-rds"}}
    assert result == expected


def test_get_replicas_info_via_defaults(mocker):
    # this test makes sure loading replica source info from defaults works
    gql_mock = mocker.patch.object(gql, "get_resource")
    gql_mock.return_value = {"content": '{"replicate_source_db": "replica-source-id"}'}
    namespace = {
        "terraformResources": [
            {
                "account": "acc",
                "identifier": "replica-id",
                "provider": "rds",
                "defaults": "defaults-ref",
            }
        ]
    }
    result = tfclient.TerraformClient.get_replicas_info([namespace])
    expected = {"acc": {"replica-id-rds": "replica-source-id-rds"}}
    assert result == expected


def test_get_replicas_info_via_overrides():
    # this test makes sure loading replica source info from overrides works
    namespace = {
        "terraformResources": [
            {
                "account": "acc",
                "identifier": "replica-id",
                "provider": "rds",
                "overrides": '{"replicate_source_db": "replica-source-id-from-override"}',
            }
        ]
    }
    result = tfclient.TerraformClient.get_replicas_info([namespace])
    expected = {"acc": {"replica-id-rds": "replica-source-id-from-override-rds"}}
    assert result == expected


def test_get_replicas_info_via_overrides_with_defaults_present(mocker):
    # defaults are present to show that overrides have precedence
    gql_mock = mocker.patch.object(gql, "get_resource")
    gql_mock.return_value = {
        "content": '{"replicate_source_db": "replica-source-id-from-defaults"}'
    }

    namespace = {
        "terraformResources": [
            {
                "account": "acc",
                "identifier": "replica-id",
                "provider": "rds",
                "defaults": "defaults-ref",
                "overrides": '{"replicate_source_db": "replica-source-id-from-override"}',
            }
        ]
    }
    result = tfclient.TerraformClient.get_replicas_info([namespace])
    expected = {"acc": {"replica-id-rds": "replica-source-id-from-override-rds"}}
    assert result == expected
