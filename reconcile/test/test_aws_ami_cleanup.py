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
from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_ec2
from pytest_mock import MockerFixture

from reconcile.aws_ami_cleanup.integration import (
    AIAmi,
    AmiTag,
    AWSAmi,
    CannotCompareTagsError,
    check_aws_ami_in_use,
    get_app_interface_amis,
    get_aws_amis,
)
from reconcile.gql_definitions.aws_ami_cleanup.asg_namespaces import (
    ASGNamespacesQueryData,
)
from reconcile.test.fixtures import Fixtures
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.terrascript_aws_client import TerrascriptClient as Terrascript

if TYPE_CHECKING:
    from mypy_boto3_ec2 import EC2Client
    from mypy_boto3_ec2.type_defs import CreateImageResultTypeDef
else:
    EC2Client = object
    CreateImageResultTypeDef = dict

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
def aws_api(accounts: list[dict[str, Any]], mocker: MockerFixture) -> AWSApi:
    mock_secret_reader = mocker.patch(
        "reconcile.utils.aws_api.SecretReader", autospec=True
    )
    mock_secret_reader.return_value.read_all.return_value = {
        "aws_access_key_id": "key_id",
        "aws_secret_access_key": "access_key",
        "region": "tf_state_bucket_region",
    }
    return AWSApi(1, accounts, init_users=False)


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
def ai_amis_fxt() -> list[AIAmi]:
    return [
        AIAmi(
            identifier="ci-int-jenkins-worker-app-sre",
            tags={
                AmiTag(key="type", value="ci-int-jenkins-worker-app-sre"),
                AmiTag(
                    key="infra_commit",
                    value="sha-0123",
                ),
            },
        ),
        AIAmi(
            identifier="ci-int-jenkins-worker-app-interface",
            tags={
                AmiTag(key="type", value="ci-int-jenkins-worker-app-interface"),
                AmiTag(
                    key="infra_commit",
                    value="sha-4567",
                ),
            },
        ),
    ]


def test_get_aws_amis_success(
    ec2_client: EC2Client,
    aws_api: AWSApi,
    rhel_image: CreateImageResultTypeDef,
    suse_image: CreateImageResultTypeDef,
) -> None:
    utc_now = datetime.utcnow() + timedelta(seconds=60)
    amis = get_aws_amis(
        aws_api=aws_api,
        ec2_client=ec2_client,
        owner=MOTO_DEFAULT_ACCOUNT,
        regex="ci-int-jenkins-worker-rhel7.*",
        age_in_seconds=30,
        utc_now=utc_now,
        region="us-east-1",
    )

    assert len(amis) == 1
    assert amis[0].image_id == rhel_image["ImageId"]


def test_get_aws_amis_unmatched_regex(
    ec2_client: EC2Client,
    aws_api: AWSApi,
    rhel_image: CreateImageResultTypeDef,
    suse_image: CreateImageResultTypeDef,
) -> None:
    utc_now = datetime.utcnow() + timedelta(seconds=60)
    amis = get_aws_amis(
        aws_api=aws_api,
        ec2_client=ec2_client,
        owner=MOTO_DEFAULT_ACCOUNT,
        regex="ci-int-jenkins-worker-centos7.*",
        age_in_seconds=30,
        utc_now=utc_now,
        region="us-east-1",
    )

    assert len(amis) == 0


def test_get_aws_amis_different_account(
    ec2_client: EC2Client,
    aws_api: AWSApi,
    rhel_image: CreateImageResultTypeDef,
    suse_image: CreateImageResultTypeDef,
) -> None:
    utc_now = datetime.utcnow() + timedelta(seconds=60)
    amis = get_aws_amis(
        aws_api=aws_api,
        ec2_client=ec2_client,
        owner="789123456789",
        regex="ci-int-jenkins-worker-rhel7.*",
        age_in_seconds=30,
        utc_now=utc_now,
        region="us-east-1",
    )

    assert len(amis) == 0


def test_get_aws_amis_too_young(
    ec2_client: EC2Client,
    aws_api: AWSApi,
    rhel_image: CreateImageResultTypeDef,
    suse_image: CreateImageResultTypeDef,
) -> None:
    utc_now = datetime.utcnow() + timedelta(seconds=60)
    amis = get_aws_amis(
        aws_api=aws_api,
        ec2_client=ec2_client,
        owner=MOTO_DEFAULT_ACCOUNT,
        regex="ci-int-jenkins-worker-rhel7.*",
        age_in_seconds=90,
        utc_now=utc_now,
        region="us-east-1",
    )

    assert len(amis) == 0


def test_get_app_interface_amis(ai_amis_fxt: list[AIAmi]) -> None:
    fixture = Fixtures("aws_ami_cleanup").get_anymarkup("namespaces.yaml")
    namespaces = ASGNamespacesQueryData(**fixture).namespaces
    ts = MagicMock(spec=Terrascript)
    ts.get_commit_sha.side_effect = ["sha-0123", "sha-4567"]

    app_interface_amis = get_app_interface_amis(namespaces, ts)
    assert app_interface_amis[0].identifier == ai_amis_fxt[0].identifier
    assert app_interface_amis[0].tags == ai_amis_fxt[0].tags
    assert app_interface_amis[1].identifier == ai_amis_fxt[1].identifier
    assert app_interface_amis[1].tags == ai_amis_fxt[1].tags


def test_check_aws_ami_in_use(ai_amis_fxt: list[AIAmi]) -> None:
    utc_now = datetime.utcnow()
    aws_ami = AWSAmi(
        name="ci-int-jenkins-worker-app-sre-sha-0123",
        image_id="ami-123456",
        creation_date=utc_now,
        tags={
            AmiTag(key="infra_commit", value="sha-0123"),
            AmiTag(key="type", value="ci-int-jenkins-worker-app-sre"),
        },
        snapshot_ids=[],
    )
    assert check_aws_ami_in_use(aws_ami, ai_amis_fxt) == "ci-int-jenkins-worker-app-sre"

    aws_ami = AWSAmi(
        name="ci-int-jenkins-worker-app-interface-sha-4567",
        image_id="ami-823445",
        creation_date=utc_now,
        tags={
            AmiTag(key="type", value="ci-int-jenkins-worker-app-interface"),
            AmiTag(key="infra_commit", value="sha-4567"),
        },
        snapshot_ids=[],
    )
    assert (
        check_aws_ami_in_use(aws_ami, ai_amis_fxt)
        == "ci-int-jenkins-worker-app-interface"
    )

    aws_ami = AWSAmi(
        name="ci-int-jenkins-worker-app-interface-a-different-sha",
        image_id="ami-823445",
        creation_date=utc_now,
        tags={
            AmiTag(key="type", value="ci-int-jenkins-worker-app-interface"),
            AmiTag(key="infra_commit", value="a-different-sha"),
        },
        snapshot_ids=[],
    )

    assert not check_aws_ami_in_use(aws_ami, ai_amis_fxt)

    aws_ami = AWSAmi(
        name="ci-int-jenkins-worker-app-interface-a-weird-one",
        image_id="ami-823445",
        creation_date=utc_now,
        tags={
            AmiTag(key="type", value="ci-int-jenkins-worker-app-interface"),
        },
        snapshot_ids=[],
    )

    with pytest.raises(CannotCompareTagsError) as excinfo:
        check_aws_ami_in_use(aws_ami, ai_amis_fxt)

    assert "AI AMI has more tags than" in str(excinfo.value)
