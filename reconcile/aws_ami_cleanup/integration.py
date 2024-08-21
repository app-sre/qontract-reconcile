import logging
import re
from collections import defaultdict
from collections.abc import (
    Callable,
)
from datetime import (
    datetime,
    timedelta,
)
from typing import (
    TYPE_CHECKING,
)

from botocore.exceptions import ClientError
from pydantic import (
    BaseModel,
)

from reconcile.gql_definitions.aws_ami_cleanup.aws_accounts import (
    AWSAccountCleanupOptionAMIV1,
    AWSAccountSharingOptionAMIV1,
)
from reconcile.gql_definitions.aws_ami_cleanup.aws_accounts import (
    query as aws_accounts_query,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils import gql
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.defer import defer
from reconcile.utils.parse_dhms_duration import dhms_to_seconds
from reconcile.utils.secret_reader import create_secret_reader

if TYPE_CHECKING:
    from mypy_boto3_ec2 import EC2Client
else:
    EC2Client = object

QONTRACT_INTEGRATION = "aws_ami_cleanup"
MANAGED_TAG = {"Key": "managed_by_integration", "Value": QONTRACT_INTEGRATION}


class AWSAmi(BaseModel):
    name: str
    image_id: str
    creation_date: datetime
    snapshot_ids: list[str]

    class Config:
        frozen = True


def get_aws_amis_from_launch_templates(ec2_client: EC2Client) -> set[str]:
    amis = set()

    paginator = ec2_client.get_paginator("describe_launch_templates")
    for page in paginator.paginate():
        for launch_template in page.get("LaunchTemplates", []):
            if launch_template_id := launch_template.get("LaunchTemplateId"):
                launch_template_versions = ec2_client.describe_launch_template_versions(
                    LaunchTemplateId=launch_template_id,
                    Versions=[str(launch_template.get("LatestVersionNumber"))],
                ).get("LaunchTemplateVersions", [])

                if launch_template_versions:
                    if (
                        ami_id := launch_template_versions[0]
                        .get("LaunchTemplateData", {})
                        .get("ImageId")
                    ):
                        amis.add(ami_id)

    return amis


def get_aws_amis(
    ec2_client: EC2Client,
    owner: str,
    regex: str,
    age_in_seconds: int,
    utc_now: datetime,
) -> list[AWSAmi]:
    """Get amis that match regex older than given age"""

    pattern = re.compile(regex)
    paginator = ec2_client.get_paginator("describe_images")
    results = []
    for page in paginator.paginate(Owners=[owner]):
        for image in page.get("Images", []):
            if not re.search(pattern, image["Name"]):
                continue

            creation_date = datetime.strptime(
                image["CreationDate"], "%Y-%m-%dT%H:%M:%S.%fZ"
            )
            current_delta = utc_now - creation_date
            delete_delta = timedelta(seconds=age_in_seconds)

            if current_delta < delete_delta:
                continue

            snapshot_ids = []
            for bdv in image["BlockDeviceMappings"]:
                ebs = bdv.get("Ebs")
                if not ebs:
                    continue

                if sid := ebs.get("SnapshotId"):
                    snapshot_ids.append(sid)

            results.append(
                AWSAmi(
                    name=image["Name"],
                    image_id=image["ImageId"],
                    creation_date=creation_date,
                    snapshot_ids=snapshot_ids,
                )
            )

    return results


def get_region(
    config_region: str | None,
    account_name: str,
    resources_default_region: str,
    supported_deployment_regions: list[str] | None,
) -> str:
    """Defines the region to search for AMIs."""
    region = config_region or resources_default_region
    if region not in (supported_deployment_regions or []):
        raise ValueError(f"region {region} is not supported in {account_name}")

    return region


@defer
def run(dry_run: bool, thread_pool_size: int, defer: Callable | None = None) -> None:
    utc_now = datetime.utcnow()
    gqlapi = gql.get_api()
    aws_accounts = aws_accounts_query(gqlapi.query).accounts

    # Get accounts that have cleanup configured
    cleanup_accounts = []
    for account in aws_accounts or []:
        if not account.cleanup:
            continue
        is_ami_related = False
        for cleanup in account.cleanup:
            is_ami_related |= cleanup.provider == "ami"
        if not is_ami_related:
            continue
        cleanup_accounts.append(account)

    # Build a dict with all accounts that are used to share amis with. Together with
    # the cleanup account we will look into the account's launch templates in order to
    # find the AMIs that are currently being used. We will make sure that those are not
    # deleted even if they have expired.
    ami_accounts = defaultdict(set)
    for account in cleanup_accounts:
        ami_accounts[account.name].add(account.resources_default_region)

        for sharing_config in account.sharing or []:
            if not isinstance(sharing_config, AWSAccountSharingOptionAMIV1):
                continue

            region = get_region(
                config_region=sharing_config.region,
                account_name=sharing_config.account.name,
                resources_default_region=sharing_config.account.resources_default_region,
                supported_deployment_regions=sharing_config.account.supported_deployment_regions,
            )

            ami_accounts[sharing_config.account.name].add(
                sharing_config.account.resources_default_region
            )

    # Build AWSApi object. We will use all those accounts listed in ami_accounts since
    # we will also need to look for used AMIs.
    accounts_dicted = [
        account.dict(by_alias=True)
        for account in aws_accounts or []
        if account.name in ami_accounts
    ]
    secret_reader = create_secret_reader(
        use_vault=get_app_interface_vault_settings().vault
    )
    aws_api = AWSApi(1, accounts_dicted, secret_reader=secret_reader, init_users=False)
    if defer:  # defer is provided by the method decorator; this makes just mypy happy.
        defer(aws_api.cleanup)

    # Get all AMIs used
    amis_used_in_launch_templates = set()
    for account_name, regions in ami_accounts.items():
        for region in regions:
            session = aws_api.get_session(account_name)
            ec2_client = aws_api.get_session_client(session, "ec2", region)
            launch_template_amis = get_aws_amis_from_launch_templates(
                ec2_client=ec2_client
            )
            if launch_template_amis:
                amis_used_in_launch_templates.update(launch_template_amis)

    # The action
    for account in cleanup_accounts:
        for cleanup_config in account.cleanup or []:
            if not isinstance(cleanup_config, AWSAccountCleanupOptionAMIV1):
                continue

            region = get_region(
                config_region=cleanup_config.region,
                account_name=account.name,
                resources_default_region=account.resources_default_region,
                supported_deployment_regions=account.supported_deployment_regions,
            )
            age_in_seconds = dhms_to_seconds(cleanup_config.age)

            session = aws_api.get_session(account.name)
            ec2_client = aws_api.get_session_client(session, "ec2", region)

            aws_amis = get_aws_amis(
                ec2_client=ec2_client,
                owner=account.uid,
                regex=cleanup_config.regex,
                age_in_seconds=age_in_seconds,
                utc_now=utc_now,
            )

            for ami in aws_amis:
                if ami.image_id in amis_used_in_launch_templates:
                    logging.info(
                        "Discarding AMI %s with id %s as it is still in use.",
                        ami.name,
                        ami.image_id,
                    )
                    continue

                logging.info(
                    "Deregistering image %s with id %s created in %s",
                    ami.name,
                    ami.image_id,
                    ami.creation_date,
                )

                try:
                    ec2_client.deregister_image(ImageId=ami.image_id, DryRun=dry_run)
                except ClientError as e:
                    if "DryRunOperation" in str(e):
                        logging.info(e)
                    else:
                        raise

                if not ami.snapshot_ids:
                    continue

                for snapshot_id in ami.snapshot_ids:
                    logging.info(
                        "Deleting associated snapshot %s from image %s",
                        snapshot_id,
                        ami.image_id,
                    )

                    try:
                        ec2_client.delete_snapshot(
                            SnapshotId=snapshot_id, DryRun=dry_run
                        )
                    except ClientError as e:
                        if "DryRunOperation" in str(e):
                            logging.info(e)
                        else:
                            raise
