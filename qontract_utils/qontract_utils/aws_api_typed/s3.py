from __future__ import annotations

from typing import TYPE_CHECKING

from qontract_utils.aws_api_typed._hooks import AWS_DEFAULT_HOOKS, AWSApiCallContext
from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


@with_hooks(hooks=AWS_DEFAULT_HOOKS)
class AWSApiS3:
    _hooks: Hooks

    def __init__(self, client: S3Client, hooks: Hooks | None = None) -> None:  # noqa: ARG002
        self.client = client

    @invoke_with_hooks(lambda: AWSApiCallContext(method="create_bucket", service="s3"))
    def create_bucket(self, name: str, region: str) -> str:
        """Create an S3 bucket without any ACLs therefore the creator will be the owner and returns the ARN."""
        bucket_kwargs = {}
        if region != "us-east-1":
            # you can't specify the location if it's us-east-1 :(
            # see valid values "LocationConstraint" here: https://docs.aws.amazon.com/AmazonS3/latest/API/API_CreateBucketConfiguration.html
            bucket_kwargs = {
                "CreateBucketConfiguration": {
                    "LocationConstraint": region,
                },
            }
        self.client.create_bucket(Bucket=name, **bucket_kwargs)  # type: ignore[arg-type]
        return f"arn:aws:s3:::{name}"
