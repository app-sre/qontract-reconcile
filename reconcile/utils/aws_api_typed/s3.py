from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_s3.literals import BucketLocationConstraintType
else:
    S3Client = BucketLocationConstraintType = object


class AWSApiS3:
    def __init__(self, client: S3Client) -> None:
        self.client = client

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
        self.client.create_bucket(Bucket=name, **bucket_kwargs)  # type: ignore
        return f"arn:aws:s3:::{name}"
