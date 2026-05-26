from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import boto3
import pytest
import responses
from moto import mock_aws

from reconcile.aws_rosa_orphan_cleanup.integration import (
    check_cluster_exists_in_ocm,
    get_rosa_ec2_instances,
    terminate_orphaned_instance,
)
from reconcile.utils.ocm_base_client import OCMBaseClient

if TYPE_CHECKING:
    from collections.abc import Generator

    from mypy_boto3_ec2 import EC2Client
    from mypy_boto3_ec2.type_defs import InstanceTypeDef


@pytest.fixture
def ec2_client() -> Generator[EC2Client, None, None]:
    with mock_aws():
        yield boto3.client("ec2", region_name="us-east-1")


@pytest.fixture
def rosa_instance(ec2_client: EC2Client) -> InstanceTypeDef:
    """Create a running EC2 instance with ROSA tags."""
    reservation = ec2_client.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.xlarge",
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [
                    {"Key": "api.openshift.com/name", "Value": "test-cluster"},
                    {"Key": "api.openshift.com/id", "Value": "cluster-123"},
                ],
            },
        ],
    )
    return reservation["Instances"][0]


@pytest.fixture
def non_rosa_instance(ec2_client: EC2Client) -> InstanceTypeDef:
    """Create a running EC2 instance without ROSA tags."""
    reservation = ec2_client.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.micro",
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [
                    {"Key": "Name", "Value": "regular-instance"},
                ],
            },
        ],
    )
    return reservation["Instances"][0]


def test_get_rosa_ec2_instances_filters_by_tags(
    ec2_client: EC2Client,
    rosa_instance: InstanceTypeDef,
    non_rosa_instance: InstanceTypeDef,
) -> None:
    """Test that only instances with ROSA tags are returned."""
    instances = get_rosa_ec2_instances(ec2_client)

    assert len(instances) == 1
    assert instances[0].instance_id == rosa_instance["InstanceId"]
    assert instances[0].cluster_name == "test-cluster"
    assert instances[0].cluster_id == "cluster-123"
    assert instances[0].instance_type == "t3.xlarge"


def test_get_rosa_ec2_instances_empty_when_no_rosa_instances(
    ec2_client: EC2Client, non_rosa_instance: InstanceTypeDef
) -> None:
    """Test that no instances are returned when there are no ROSA instances."""
    instances = get_rosa_ec2_instances(ec2_client)

    assert len(instances) == 0


@responses.activate
def test_check_cluster_exists_in_ocm_returns_true_when_exists() -> None:
    """Test that check_cluster_exists_in_ocm returns True when cluster exists."""
    responses.post(
        "https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token",
        json={"access_token": "test-token"},
        status=200,
    )
    responses.get(
        "https://api.openshift.com/api/clusters_mgmt/v1/clusters/cluster-123",
        json={"id": "cluster-123", "name": "test-cluster"},
        status=200,
    )

    ocm_client = OCMBaseClient(
        url="https://api.openshift.com",
        access_token_client_secret="test-secret",
        access_token_url="https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token",
        access_token_client_id="test-client-id",
    )

    exists = check_cluster_exists_in_ocm(ocm_client, "cluster-123", "test-cluster")

    assert exists is True


@responses.activate
def test_check_cluster_exists_in_ocm_returns_false_on_404() -> None:
    """Test that check_cluster_exists_in_ocm returns False when cluster is deleted (404)."""
    responses.post(
        "https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token",
        json={"access_token": "test-token"},
        status=200,
    )
    responses.get(
        "https://api.openshift.com/api/clusters_mgmt/v1/clusters/cluster-123",
        json={"kind": "Error", "id": "404", "reason": "Cluster not found"},
        status=404,
    )

    ocm_client = OCMBaseClient(
        url="https://api.openshift.com",
        access_token_client_secret="test-secret",
        access_token_url="https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token",
        access_token_client_id="test-client-id",
    )

    exists = check_cluster_exists_in_ocm(ocm_client, "cluster-123", "test-cluster")

    assert exists is False


@responses.activate
def test_check_cluster_exists_in_ocm_returns_true_when_no_cluster_id() -> None:
    """Test that check_cluster_exists_in_ocm returns True when cluster_id is None."""
    responses.post(
        "https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token",
        json={"access_token": "test-token"},
        status=200,
    )

    ocm_client = OCMBaseClient(
        url="https://api.openshift.com",
        access_token_client_secret="test-secret",
        access_token_url="https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token",
        access_token_client_id="test-client-id",
    )

    exists = check_cluster_exists_in_ocm(ocm_client, None, "test-cluster")

    assert exists is True


def test_terminate_orphaned_instance_dry_run(
    ec2_client: EC2Client, rosa_instance: InstanceTypeDef
) -> None:
    """Test that terminate_orphaned_instance with dry_run=True does not terminate instance."""
    from reconcile.aws_rosa_orphan_cleanup.integration import OrphanedInstance

    instance = OrphanedInstance(
        instance_id=rosa_instance["InstanceId"],
        instance_type="t3.xlarge",
        launch_time=datetime.now(tz=UTC),
        cluster_name="test-cluster",
        cluster_id="cluster-123",
        tags={},
    )

    terminate_orphaned_instance(ec2_client, instance, dry_run=True)

    response = ec2_client.describe_instances(InstanceIds=[rosa_instance["InstanceId"]])
    state = response["Reservations"][0]["Instances"][0]["State"]["Name"]
    assert state == "running"


def test_terminate_orphaned_instance_real(
    ec2_client: EC2Client, rosa_instance: InstanceTypeDef
) -> None:
    """Test that terminate_orphaned_instance with dry_run=False terminates instance."""
    from reconcile.aws_rosa_orphan_cleanup.integration import OrphanedInstance

    instance = OrphanedInstance(
        instance_id=rosa_instance["InstanceId"],
        instance_type="t3.xlarge",
        launch_time=datetime.now(tz=UTC),
        cluster_name="test-cluster",
        cluster_id="cluster-123",
        tags={},
    )

    terminate_orphaned_instance(ec2_client, instance, dry_run=False)

    response = ec2_client.describe_instances(InstanceIds=[rosa_instance["InstanceId"]])
    state = response["Reservations"][0]["Instances"][0]["State"]["Name"]
    assert state in {"shutting-down", "terminated"}
