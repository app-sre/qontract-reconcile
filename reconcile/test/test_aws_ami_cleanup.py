# pylint does not consider frozen BaseModels as hashable and then complains that they cannot
# be members of a set.
# pylint: disable=unhashable-member

from collections.abc import Generator
from datetime import (
    datetime,
    timedelta,
)
from typing import (
    TYPE_CHECKING,
    Any,
)

import boto3
import pytest
from moto import mock_ec2

from reconcile.aws_ami_cleanup.integration import (
    get_aws_amis,
    get_aws_amis_from_launch_templates,
)

if TYPE_CHECKING:
    from mypy_boto3_ec2 import EC2Client
    from mypy_boto3_ec2.type_defs import (
        CreateImageResultTypeDef,
        LaunchTemplateVersionTypeDef,
    )
else:
    EC2Client = object
    CreateImageResultTypeDef = dict
    LaunchTemplateVersionTypeDef = dict

MOTO_DEFAULT_ACCOUNT = "123456789012"


@pytest.fixture
def accounts() -> list[dict[str, Any]]:
    return [
        {
            "name": "some-account",
            "automationToken": {
                "path": "path",
            },
            "resourcesDefaultRegion": "default-region",
        }
    ]


@pytest.fixture
def ec2_client() -> Generator[EC2Client, None, None]:
    with mock_ec2():
        yield boto3.client("ec2", region_name="us-east-1")


@pytest.fixture
def rhel_image(ec2_client: EC2Client) -> CreateImageResultTypeDef:
    # RHEL7 ami from moto/ec2/resources/amis.json
    reservation = ec2_client.run_instances(
        ImageId="ami-bb9a6bc2", MinCount=1, MaxCount=1
    )
    instance_id = reservation["Instances"][0]["InstanceId"]

    return ec2_client.create_image(
        InstanceId=instance_id,
        Name="ci-int-jenkins-worker-rhel7-sha-123456",
        TagSpecifications=[
            {
                "ResourceType": "image",
                "Tags": [
                    {"Key": "infra_commit", "Value": "sha-123456"},
                    {"Key": "type", "Value": "ci-int-jenkins-worker-rhel7"},
                ],
            },
        ],
    )


@pytest.fixture
def suse_image(ec2_client: EC2Client) -> CreateImageResultTypeDef:
    # SUSE AMI from moto/ec2/resources/amis.json
    reservation = ec2_client.run_instances(
        ImageId="ami-35e92e4c", MinCount=1, MaxCount=1
    )
    instance_id = reservation["Instances"][0]["InstanceId"]

    return ec2_client.create_image(
        InstanceId=instance_id,
        Name="ci-int-jenkins-worker-suse12-sha-789012",
        TagSpecifications=[
            {
                "ResourceType": "image",
                "Tags": [
                    {"Key": "infra_commit", "Value": "sha-789012"},
                    {"Key": "arch", "Value": "ci-int-jenkins-worker-suse12"},
                ],
            },
        ],
    )


@pytest.fixture
def ubuntu_launch_template(ec2_client: EC2Client) -> LaunchTemplateVersionTypeDef:
    # Ubuntu AMI from moto/ec2/resources/amis.json
    response = ec2_client.create_launch_template(
        LaunchTemplateName="Ubuntu",
        LaunchTemplateData={
            "ImageId": "ami-1e749f67",  # Canonical, Ubuntu, 14.04 LTS
            "InstanceType": "t3.micro",
            "SecurityGroupIds": ["sg-12345678"],
        },
    )

    return ec2_client.describe_launch_template_versions(
        LaunchTemplateId=response["LaunchTemplate"]["LaunchTemplateId"],
        Versions=["1"],
    )["LaunchTemplateVersions"][0]


@pytest.fixture
def suse_launch_template(ec2_client: EC2Client) -> LaunchTemplateVersionTypeDef:
    # SUSE AMI from moto/ec2/resources/amis.json
    response = ec2_client.create_launch_template(
        LaunchTemplateName="SUSE",
        LaunchTemplateData={
            "ImageId": "ami-35e92e4c",  # SUSE Linux Enterprise Server 12 SP3
            "InstanceType": "t3.micro",
            "SecurityGroupIds": ["sg-12345678"],
        },
    )

    return ec2_client.describe_launch_template_versions(
        LaunchTemplateId=response["LaunchTemplate"]["LaunchTemplateId"],
        Versions=["1"],
    )["LaunchTemplateVersions"][0]


def test_get_aws_amis_success(
    ec2_client: EC2Client,
    rhel_image: CreateImageResultTypeDef,
    suse_image: CreateImageResultTypeDef,
) -> None:
    utc_now = datetime.utcnow() + timedelta(seconds=60)
    amis = get_aws_amis(
        ec2_client=ec2_client,
        owner=MOTO_DEFAULT_ACCOUNT,
        regex="ci-int-jenkins-worker-rhel7.*",
        age_in_seconds=30,
        utc_now=utc_now,
    )

    assert len(amis) == 1
    assert amis[0].image_id == rhel_image["ImageId"]


def test_get_aws_amis_unmatched_regex(
    ec2_client: EC2Client,
    rhel_image: CreateImageResultTypeDef,
    suse_image: CreateImageResultTypeDef,
) -> None:
    utc_now = datetime.utcnow() + timedelta(seconds=60)
    amis = get_aws_amis(
        ec2_client=ec2_client,
        owner=MOTO_DEFAULT_ACCOUNT,
        regex="ci-int-jenkins-worker-centos7.*",
        age_in_seconds=30,
        utc_now=utc_now,
    )

    assert len(amis) == 0


def test_get_aws_amis_different_account(
    ec2_client: EC2Client,
    rhel_image: CreateImageResultTypeDef,
    suse_image: CreateImageResultTypeDef,
) -> None:
    utc_now = datetime.utcnow() + timedelta(seconds=60)
    amis = get_aws_amis(
        ec2_client=ec2_client,
        owner="789123456789",
        regex="ci-int-jenkins-worker-rhel7.*",
        age_in_seconds=30,
        utc_now=utc_now,
    )

    assert len(amis) == 0


def test_get_aws_amis_too_young(
    ec2_client: EC2Client,
    rhel_image: CreateImageResultTypeDef,
    suse_image: CreateImageResultTypeDef,
) -> None:
    utc_now = datetime.utcnow() + timedelta(seconds=60)
    amis = get_aws_amis(
        ec2_client=ec2_client,
        owner=MOTO_DEFAULT_ACCOUNT,
        regex="ci-int-jenkins-worker-rhel7.*",
        age_in_seconds=90,
        utc_now=utc_now,
    )

    assert len(amis) == 0


def test_get_aws_amis_from_launch_templates(
    ec2_client: EC2Client,
    ubuntu_launch_template: LaunchTemplateVersionTypeDef,
    suse_launch_template: LaunchTemplateVersionTypeDef,
) -> None:
    amis = get_aws_amis_from_launch_templates(ec2_client)
    assert amis == {
        ubuntu_launch_template["LaunchTemplateData"]["ImageId"],
        suse_launch_template["LaunchTemplateData"]["ImageId"],
    }

    # create a new ubuntu version
    new_ami_id = "ami-785db401"  # "Canonical, Ubuntu, 16.04 LTS
    ec2_client.create_launch_template_version(
        LaunchTemplateId=ubuntu_launch_template["LaunchTemplateId"],
        LaunchTemplateData={"ImageId": new_ami_id},
    )

    amis = get_aws_amis_from_launch_templates(ec2_client)
    assert amis == {
        new_ami_id,
        suse_launch_template["LaunchTemplateData"]["ImageId"],
    }
