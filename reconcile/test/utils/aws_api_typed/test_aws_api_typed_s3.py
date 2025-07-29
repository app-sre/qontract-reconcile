from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from reconcile.utils.aws_api_typed.s3 import AWSApiS3

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from mypy_boto3_s3 import S3Client
    from pytest_mock import MockerFixture


@pytest.fixture
def s3_client(mocker: MockerFixture) -> S3Client:
    return mocker.Mock()


@pytest.fixture
def aws_api_s3(s3_client: S3Client) -> AWSApiS3:
    return AWSApiS3(client=s3_client)


def test_aws_api_typed_iam_create_bucket_us_east_1(
    aws_api_s3: AWSApiS3, s3_client: MagicMock
) -> None:
    assert (
        aws_api_s3.create_bucket(name="bucket", region="us-east-1")
        == "arn:aws:s3:::bucket"
    )
    s3_client.create_bucket.assert_called_once_with(Bucket="bucket")


def test_aws_api_typed_iam_create_bucket_other_region(
    aws_api_s3: AWSApiS3, s3_client: MagicMock
) -> None:
    assert (
        aws_api_s3.create_bucket(name="bucket", region="us-east-2")
        == "arn:aws:s3:::bucket"
    )
    s3_client.create_bucket.assert_called_once_with(
        Bucket="bucket", CreateBucketConfiguration={"LocationConstraint": "us-east-2"}
    )
