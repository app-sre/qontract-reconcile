import logging
import re
import sys
from collections.abc import (
    Callable,
    Mapping,
)
from datetime import (
    datetime,
    timedelta,
)
from typing import (
    TYPE_CHECKING,
    Any,
    Optional,
)

from botocore.exceptions import ClientError
from pydantic import (
    BaseModel,
    Field,
)

from reconcile import queries
from reconcile.gql_definitions.aws_ami_cleanup.asg_namespaces import (
    ASGImageGitV1,
    ASGImageStaticV1,
    NamespaceTerraformProviderResourceAWSV1,
    NamespaceTerraformResourceASGV1,
    NamespaceV1,
)
from reconcile.gql_definitions.aws_ami_cleanup.asg_namespaces import (
    query as query_asg_namespaces,
)
from reconcile.status import ExitCodes
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils import gql
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.defer import defer
from reconcile.utils.parse_dhms_duration import dhms_to_seconds
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.terrascript_aws_client import TerrascriptClient as Terrascript

if TYPE_CHECKING:
    from mypy_boto3_ec2 import EC2Client
else:
    EC2Client = object

QONTRACT_INTEGRATION = "aws_ami_cleanup"
MANAGED_TAG = {"Key": "managed_by_integration", "Value": QONTRACT_INTEGRATION}


class CannotCompareTagsError(Exception):
    pass


class AmiTag(BaseModel):
    key: str = Field(alias="Key")
    value: str = Field(alias="Value")

    class Config:
        allow_population_by_field_name = True
        frozen = True


class AWSAmi(BaseModel):
    name: str
    image_id: str
    tags: set[AmiTag]
    creation_date: datetime
    snapshot_ids: list[str]

    class Config:
        frozen = True


class AIAmi(BaseModel):
    identifier: str
    tags: set[AmiTag]

    class Config:
        frozen = True


def get_aws_amis(
    aws_api: AWSApi,
    ec2_client: EC2Client,
    owner: str,
    regex: str,
    age_in_seconds: int,
    utc_now: datetime,
    region: str,
) -> list[AWSAmi]:
    """Get amis that match regex older than given age"""

    images = aws_api.paginate(
        ec2_client, "describe_images", "Images", {"Owners": [owner]}
    )

    pattern = re.compile(regex)
    results = []
    for i in images:
        if not re.search(pattern, i["Name"]):
            continue

        creation_date = datetime.strptime(i["CreationDate"], "%Y-%m-%dT%H:%M:%S.%fZ")
        current_delta = utc_now - creation_date
        delete_delta = timedelta(seconds=age_in_seconds)

        if current_delta < delete_delta:
            continue

        # We have nothing to do with untagged AMIs since we will need tags to verify if AMI are
        # in use or not.
        if not i.get("Tags"):
            continue

        snapshot_ids = []
        for bdv in i["BlockDeviceMappings"]:
            ebs = bdv.get("Ebs")
            if not ebs:
                continue

            if sid := ebs.get("SnapshotId"):
                snapshot_ids.append(sid)

        tags = {AmiTag(**tag) for tag in i.get("Tags")}
        results.append(
            AWSAmi(
                name=i["Name"],
                image_id=i["ImageId"],
                tags=tags,
                creation_date=creation_date,
                snapshot_ids=snapshot_ids,
            )
        )

    return results


def get_region(
    cleanup: Mapping[str, Any],
    account: Mapping[str, Any],
) -> str:
    """Defines the region to search for AMIs."""
    region = cleanup.get("region") or account["resourcesDefaultRegion"]
    if region not in account["supportedDeploymentRegions"]:
        raise ValueError(f"region {region} is not supported in {account['name']}")

    return region


def get_app_interface_amis(
    namespaces: Optional[list[NamespaceV1]], ts: Terrascript
) -> list[AIAmi]:
    """Returns all the ami referenced in ASGs in app-interface."""
    app_interface_amis = []
    for n in namespaces or []:
        for er in n.external_resources or []:
            if not isinstance(er, NamespaceTerraformProviderResourceAWSV1):
                continue

            for r in er.resources:
                if not isinstance(r, NamespaceTerraformResourceASGV1):
                    continue

                tags = set()
                for i in r.image:
                    if isinstance(i, ASGImageGitV1):
                        tags.add(
                            AmiTag(
                                key=i.tag_name,
                                value=ts.get_commit_sha(i.dict(by_alias=True)),
                            )
                        )
                    elif isinstance(i, ASGImageStaticV1):
                        tags.add(AmiTag(key=i.tag_name, value=i.value))

                app_interface_amis.append(AIAmi(identifier=r.identifier, tags=tags))

    return app_interface_amis


def check_aws_ami_in_use(
    aws_ami: AWSAmi, app_interface_amis: list[AIAmi]
) -> Optional[str]:
    """Verifies if the given AWS ami is in use in a defined app-interface ASG."""
    for ai_ami in app_interface_amis:
        # This can happen if the ASG init template has changed over the time. We don't have a way
        # to properly delete these automatically since we cannot assure they are not in use.
        # The integration will fail in this case and these amis will need to be handled manually.
        if len(ai_ami.tags) > len(aws_ami.tags):
            raise CannotCompareTagsError(
                f"{ai_ami.identifier} AI AMI has more tags than {aws_ami.image_id} AWS AMI"
            )

        if ai_ami.tags.issubset(aws_ami.tags):
            return ai_ami.identifier

    return None


@defer
def run(dry_run: bool, thread_pool_size: int, defer: Optional[Callable] = None) -> None:
    exit_code = ExitCodes.SUCCESS

    # We still use here a non-typed query; accounts is passed to AWSApi and Terrascript classes
    # which contain a vast amount of magic based on keys from that dict. Since this integration
    # cannot still be properly monitored (see https://issues.redhat.com/browse/APPSRE-7674),
    # it's easy that it breaks without being noticed. Once it is properly monitored, this should
    # be moved to a typed query.
    cleanup_accounts = [
        a
        for a in queries.get_aws_accounts(terraform_state=True, cleanup=True)
        if a.get("cleanup")
    ]

    vault_settings = get_app_interface_vault_settings()

    ts = Terrascript(
        QONTRACT_INTEGRATION,
        "",
        thread_pool_size,
        cleanup_accounts,
        settings=vault_settings.dict(by_alias=True),
    )

    gqlapi = gql.get_api()
    namespaces = query_asg_namespaces(query_func=gqlapi.query).namespaces or []
    app_interface_amis = get_app_interface_amis(namespaces, ts)

    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    aws_api = AWSApi(1, cleanup_accounts, secret_reader=secret_reader, init_users=False)
    if defer:  # defer is provided by the method decorator; this makes just mypy happy.
        defer(aws_api.cleanup)

    utc_now = datetime.utcnow()
    for account in cleanup_accounts:
        for cleanup in account["cleanup"]:
            if cleanup["provider"] != "ami":
                continue

            region = get_region(cleanup, account)
            regex = cleanup["regex"]
            age_in_seconds = dhms_to_seconds(cleanup["age"])

            session = aws_api.get_session(account["name"])
            ec2_client = aws_api.get_session_client(session, "ec2", region)

            amis = get_aws_amis(
                aws_api=aws_api,
                ec2_client=ec2_client,
                owner=account["uid"],
                regex=regex,
                age_in_seconds=age_in_seconds,
                utc_now=utc_now,
                region=region,
            )

            for aws_ami in amis:
                try:
                    if identifier := check_aws_ami_in_use(aws_ami, app_interface_amis):
                        logging.info(
                            "Discarding ami %s with id %s as it is used in app-interface in %s",
                            aws_ami.name,
                            aws_ami.image_id,
                            identifier,
                        )
                        continue
                except CannotCompareTagsError as e:
                    logging.error(e)
                    if not dry_run:
                        exit_code = ExitCodes.ERROR
                    continue

                logging.info(
                    "Deregistering image %s with id %s created in %s",
                    aws_ami.name,
                    aws_ami.image_id,
                    aws_ami.creation_date,
                )

                try:
                    ec2_client.deregister_image(
                        ImageId=aws_ami.image_id, DryRun=dry_run
                    )
                except ClientError as e:
                    if "DryRunOperation" in str(e):
                        logging.info(e)
                    else:
                        raise

                if not aws_ami.snapshot_ids:
                    continue

                for snapshot_id in aws_ami.snapshot_ids:
                    logging.info(
                        "Deleting associated snapshot %s from image %s",
                        snapshot_id,
                        aws_ami.image_id,
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

    sys.exit(exit_code)
