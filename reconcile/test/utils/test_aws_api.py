from collections.abc import Generator
from typing import TYPE_CHECKING, cast

import boto3
import pytest
from moto import (
    mock_ec2,
    mock_iam,
    mock_route53,
)
from pytest_mock import MockerFixture

from reconcile.utils.aws_api import AmiTag, AWSApi

if TYPE_CHECKING:
    from mypy_boto3_ec2 import EC2Client
    from mypy_boto3_ec2.type_defs import ImageTypeDef
    from mypy_boto3_iam import IAMClient
    from mypy_boto3_route53 import Route53Client
    from mypy_boto3_route53.type_defs import (
        ChangeBatchTypeDef,
        HostedZoneTypeDef,
        ResourceRecordSetTypeDef,
        ResourceRecordTypeDef,
    )

else:
    EC2Client = IAMClient = ImageTypeDef = Route53Client = ResourceRecordTypeDef = (
        HostedZoneTypeDef
    ) = ChangeBatchTypeDef = ResourceRecordSetTypeDef = object


@pytest.fixture
def accounts() -> list[dict]:
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
def aws_api(accounts: list[dict], mocker: MockerFixture) -> AWSApi:
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
def iam_client() -> Generator[IAMClient]:
    with mock_iam():
        iam_client = boto3.client("iam")
        yield iam_client


def test_get_user_key_list(aws_api: AWSApi, iam_client: IAMClient) -> None:
    iam_client.create_user(UserName="user")
    iam_client.create_access_key(UserName="user")
    key_list = aws_api._get_user_key_list(iam_client, "user")
    assert key_list != []


def test_get_user_key_list_empty(aws_api: AWSApi, iam_client: IAMClient) -> None:
    iam_client.create_user(UserName="user")
    key_list = aws_api._get_user_key_list(iam_client, "user")
    assert key_list == []


def test_get_user_key_list_missing_user(aws_api: AWSApi, iam_client: IAMClient) -> None:
    iam_client.create_user(UserName="user1")
    key_list = aws_api._get_user_key_list(iam_client, "user2")
    assert key_list == []


def test_get_user_keys(aws_api: AWSApi, iam_client: IAMClient) -> None:
    iam_client.create_user(UserName="user")
    iam_client.create_access_key(UserName="user")
    keys = aws_api.get_user_keys(iam_client, "user")
    assert keys != []


def test_get_user_keys_empty(aws_api: AWSApi, iam_client: IAMClient) -> None:
    iam_client.create_user(UserName="user")
    keys = aws_api.get_user_keys(iam_client, "user")
    assert keys == []


def test_get_user_key_status(aws_api: AWSApi, iam_client: IAMClient) -> None:
    iam_client.create_user(UserName="user")
    iam_client.create_access_key(UserName="user")
    key = aws_api.get_user_keys(iam_client, "user")[0]
    status = aws_api.get_user_key_status(iam_client, "user", key)
    assert status == "Active"


def test_default_region(aws_api: AWSApi, accounts: list[dict]) -> None:
    for a in accounts:
        assert aws_api.sessions[a["name"]].region_name == a["resourcesDefaultRegion"]


def test_filter_amis_regex(aws_api: AWSApi) -> None:
    regex = "^match.*$"
    images = [
        cast(
            ImageTypeDef,
            {"Name": "match-regex", "ImageId": "id1", "State": "available", "Tags": []},
        ),
        cast(
            ImageTypeDef,
            {
                "Name": "no-match-regex",
                "ImageId": "id2",
                "State": "available",
                "Tags": [],
            },
        ),
    ]
    results = aws_api._filter_amis(images, regex)
    expected = {"image_id": "id1", "tags": []}
    assert results == [expected]


def test_filter_amis_state(aws_api: AWSApi) -> None:
    regex = "^match.*$"
    images = [
        cast(
            ImageTypeDef,
            {
                "Name": "match-regex-1",
                "ImageId": "id1",
                "State": "available",
                "Tags": [],
            },
        ),
        cast(
            ImageTypeDef,
            {
                "Name": "match-regex-2",
                "ImageId": "id2",
                "State": "pending",
                "Tags": [],
            },
        ),
    ]
    results = aws_api._filter_amis(images, regex)
    expected = {"image_id": "id1", "tags": []}
    assert results == [expected]


@pytest.fixture
def route53_client() -> Generator[Route53Client]:
    with mock_route53():
        route53_client = boto3.client("route53")
        yield route53_client


def test_get_hosted_zone_id(aws_api: AWSApi) -> None:
    zone_id = "THISISTHEZONEID"
    zone = cast(
        HostedZoneTypeDef,
        {
            "Name": "test",
            "Id": f"/hostedzone/{zone_id}",
            "CallerReference": "test",
        },
    )
    result = aws_api._get_hosted_zone_id(zone)
    assert result == zone_id


def test_get_hosted_zone_record_sets_empty(
    aws_api: AWSApi, route53_client: Route53Client
) -> None:
    zone_name = "test.example.com."
    results = aws_api._get_hosted_zone_record_sets(route53_client, zone_name)
    assert results == []


def test_get_hosted_zone_record_sets_exists(
    aws_api: AWSApi, route53_client: Route53Client
) -> None:
    zone_name = "test.example.com."
    route53_client.create_hosted_zone(Name=zone_name, CallerReference="test")
    zones = route53_client.list_hosted_zones_by_name(DNSName=zone_name)["HostedZones"]
    zone_id = aws_api._get_hosted_zone_id(zones[0])
    record_set = cast(
        ResourceRecordSetTypeDef,
        {
            "Name": zone_name,
            "Type": "NS",
            "ResourceRecords": [{"Value": "ns"}],
        },
    )
    change_batch = cast(
        ChangeBatchTypeDef,
        {"Changes": [{"Action": "CREATE", "ResourceRecordSet": record_set}]},
    )
    route53_client.change_resource_record_sets(
        HostedZoneId=zone_id, ChangeBatch=change_batch
    )
    results = aws_api._get_hosted_zone_record_sets(route53_client, zone_name)
    assert results == [record_set]


def test_filter_record_sets(aws_api: AWSApi) -> None:
    zone_name = "a"
    expected = cast(ResourceRecordSetTypeDef, {"Name": f"{zone_name}.", "Type": "NS"})
    record_sets = [
        expected,
        cast(ResourceRecordSetTypeDef, {"Name": f"{zone_name}.", "Type": "SOA"}),
        cast(ResourceRecordSetTypeDef, {"Name": f"not-{zone_name}.", "Type": "NS"}),
    ]
    results = aws_api._filter_record_sets(record_sets, zone_name, "NS")
    assert results == [expected]


def test_extract_records(aws_api: AWSApi) -> None:
    record = "ns.example.com"
    resource_records = [
        cast(ResourceRecordTypeDef, {"Value": f"{record}."}),
    ]
    results = aws_api._extract_records(resource_records)
    assert results == [record]


@pytest.fixture
def ec2_client() -> Generator[EC2Client]:
    with mock_ec2():
        yield boto3.client("ec2", region_name="us-east-1")


def test_get_image_id(ec2_client: EC2Client, aws_api: AWSApi) -> None:
    # RHEL7 ami from moto/ec2/resources/amis.json
    reservation = ec2_client.run_instances(
        ImageId="ami-bb9a6bc2", MinCount=1, MaxCount=1
    )
    instance_id = reservation["Instances"][0]["InstanceId"]

    # just another image which shouldn't be returned
    ec2_client.create_image(InstanceId=instance_id, Name="image-1")
    # arch=x86_64 image
    ami_x86_64 = ec2_client.create_image(
        InstanceId=instance_id,
        Name="x86_64",
        TagSpecifications=[
            {
                "ResourceType": "image",
                "Tags": [
                    {"Key": "foo", "Value": "bar"},
                    {"Key": "commit", "Value": "sha-123456"},
                    {"Key": "arch", "Value": "x86_64"},
                ],
            },
        ],
    )["ImageId"]
    # arch=aarch64 image
    ami_aarch64 = ec2_client.create_image(
        InstanceId=instance_id,
        Name="aarch64",
        TagSpecifications=[
            {
                "ResourceType": "image",
                "Tags": [
                    {"Key": "foo", "Value": "bar"},
                    {"Key": "commit", "Value": "sha-123456"},
                    {"Key": "arch", "Value": "aarch64"},
                ],
            },
        ],
    )["ImageId"]

    # just one tag
    assert (
        aws_api.get_image_id(
            "some-account", "us-east-1", tags=[AmiTag(name="arch", value="x86_64")]
        )
        == ami_x86_64
    )
    # multiple tags
    assert (
        aws_api.get_image_id(
            "some-account",
            "us-east-1",
            tags=[
                AmiTag(name="commit", value="sha-123456"),
                AmiTag(name="arch", value="aarch64"),
            ],
        )
        == ami_aarch64
    )
    # multiple amis returned ... error
    with pytest.raises(ValueError):
        aws_api.get_image_id(
            "some-account", "us-east-1", tags=[AmiTag(name="foo", value="bar")]
        )


def test_get_db_valid_upgrade_target(
    aws_api: AWSApi,
    accounts: list,
    mocker: MockerFixture,
) -> None:
    # should patch Session object, but here aws_api is already created, require bigger refactor to do proper mock
    mocker.patch.object(aws_api, "get_session_client", autospec=True)
    mocked_rds_client = aws_api.get_session_client.return_value  # type: ignore[attr-defined]
    expected_valid_upgrade_target = [
        {
            "Engine": "postgres",
            "EngineVersion": "12.9",
            "IsMajorVersionUpgrade": False,
        },
    ]
    mocked_rds_client.describe_db_engine_versions.return_value = {
        "DBEngineVersions": [{"ValidUpgradeTarget": expected_valid_upgrade_target}]
    }

    engine = "postgres"
    engine_version = "12.8"

    result = aws_api.get_db_valid_upgrade_target(
        accounts[0]["name"],
        engine,
        engine_version,
    )

    assert result == expected_valid_upgrade_target

    mocked_rds_client.describe_db_engine_versions.assert_called_once_with(
        Engine=engine,
        EngineVersion=engine_version,
        IncludeAll=True,
    )


def test_get_db_valid_upgrade_target_with_empty_db_engine_versions(
    aws_api: AWSApi,
    accounts: list,
    mocker: MockerFixture,
) -> None:
    # should patch Session object, but here aws_api is already created, require bigger refactor to do proper mock
    mocker.patch.object(aws_api, "get_session_client", autospec=True)
    mocked_rds_client = aws_api.get_session_client.return_value  # type: ignore[attr-defined]
    mocked_rds_client.describe_db_engine_versions.return_value = {
        "DBEngineVersions": []
    }

    result = aws_api.get_db_valid_upgrade_target(
        accounts[0]["name"],
        "postgres",
        "12.8",
    )

    assert result == []


def test_get_cloudwatch_log_group_tags(
    aws_api: AWSApi,
    accounts: list,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(aws_api, "get_session_client", autospec=True)
    mocked_cloudwatch_client = aws_api.get_session_client.return_value  # type: ignore[attr-defined]
    mocked_cloudwatch_client.list_tags_for_resource.return_value = {
        "tags": {
            "tag1": "value1",
        }
    }

    result = aws_api.get_cloudwatch_log_group_tags(
        accounts[0]["name"],
        "some-arn:*",
        "us-east-1",
    )

    assert result == {"tag1": "value1"}
    mocked_cloudwatch_client.list_tags_for_resource.assert_called_once_with(
        resourceArn="some-arn"
    )


def test_create_cloudwatch_tag(
    aws_api: AWSApi,
    accounts: list,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(aws_api, "get_session_client", autospec=True)
    mocked_cloudwatch_client = aws_api.get_session_client.return_value  # type: ignore[attr-defined]
    new_tag = {"tag1": "value1"}

    aws_api.create_cloudwatch_tag(
        accounts[0]["name"],
        "some-arn:*",
        new_tag,
        "us-east-1",
    )

    mocked_cloudwatch_client.tag_resource.assert_called_once_with(
        resourceArn="some-arn",
        tags=new_tag,
    )


def test_delete_cloudwatch_log_group(
    aws_api: AWSApi,
    accounts: list,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(aws_api, "get_session_client", autospec=True)
    mocked_cloudwatch_client = aws_api.get_session_client.return_value  # type: ignore[attr-defined]

    aws_api.delete_cloudwatch_log_group(
        accounts[0]["name"],
        "some-name",
        "us-east-1",
    )

    mocked_cloudwatch_client.delete_log_group.assert_called_once_with(
        logGroupName="some-name",
    )


# Ensure get_cluster_vpc_detail raises AWS exceptions and does not catch them
# This is essential so we do not end up removing peerings in terraform due to some AWS error
def test_get_cluster_vpc_details_aws_error(
    mocker: MockerFixture, aws_api: AWSApi
) -> None:
    get_account_vpcs = mocker.patch.object(aws_api, "get_account_vpcs")
    exc_txt = "Something bad happens on AWS"
    get_account_vpcs.side_effect = Exception(exc_txt)
    with pytest.raises(Exception, match=exc_txt):
        aws_api.get_cluster_vpc_details({
            "name": "some-account",
            "assume_region": "us-east-1",
        })


def test_get_cluster_vpc_details_no_endpoints(
    mocker: MockerFixture, aws_api: AWSApi
) -> None:
    expected_vpc_id = "id"
    mocker.patch.object(
        aws_api,
        "get_account_vpcs",
        return_value=[
            {
                "CidrBlock": "cidr",
                "VpcId": expected_vpc_id,
            }
        ],
    )
    mocker.patch.object(
        AWSApi,
        "_get_vpc_endpoints",
        return_value=[],
    )

    vpc_id, route_table_ids, subnets_id_az, api_security_group_id = (
        aws_api.get_cluster_vpc_details(
            {
                "name": "some-account",
                "assume_region": "us-east-1",
                "assume_cidr": "cidr",
            },
            hcp_vpc_endpoint_sg=True,
        )
    )

    assert vpc_id == expected_vpc_id
    assert route_table_ids is None
    assert subnets_id_az is None
    assert api_security_group_id is None


@pytest.mark.parametrize(
    "group_name",
    [
        "abc-default-sg",
        "abc-vpce-private-router",
    ],
)
def test_get_cluster_vpc_details_with_hcp_security_group(
    mocker: MockerFixture,
    aws_api: AWSApi,
    group_name: str,
) -> None:
    expected_vpc_id = "id"
    expected_sg_id = "sg-id"
    mocker.patch.object(
        aws_api,
        "get_account_vpcs",
        return_value=[
            {
                "CidrBlock": "cidr",
                "VpcId": expected_vpc_id,
            }
        ],
    )
    mocker.patch.object(
        AWSApi,
        "_get_vpc_endpoints",
        return_value=[
            {
                "VpcEndpointId": "vpce-id",
                "Groups": [
                    {
                        "GroupName": group_name,
                        "GroupId": expected_sg_id,
                    }
                ],
            }
        ],
    )

    vpc_id, route_table_ids, subnets_id_az, api_security_group_id = (
        aws_api.get_cluster_vpc_details(
            {
                "name": "some-account",
                "assume_region": "us-east-1",
                "assume_cidr": "cidr",
            },
            hcp_vpc_endpoint_sg=True,
        )
    )

    assert vpc_id == expected_vpc_id
    assert route_table_ids is None
    assert subnets_id_az is None
    assert api_security_group_id == expected_sg_id
