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
from reconcile.gql_definitions import (
    ASGImageGitV1,
    ASGImageStaticV1,
    NamespaceTerraformProviderResourceAWSV1,
    NamespaceTerraformResourceASGV1,
    NamespaceV1,
    AWSAccountV1,
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

QONTRACT_INTEGRATION = "aws_cloudwatch_log_retention"
MANAGED_TAG = {"Key": "managed_by_integration", "Value": QONTRACT_INTEGRATION}

class AWSCloudwatchLogRetention(BaseModel):
    name: str
    acct_uid: str
    log_regex: str
    log_retention_day_length: str

def get_app_interface_cloudwatch_retention_period():
        # aws_accounts: list[AWSAccountV1] = query_data.

    # for aws_account in aws_accounts:
    #     logging.debug("this is the aws_account var")
    #     logging.debug(aws_account)

    aws_accounts = get_aws_accounts(cleanup=True)
    results = []
    for aws_acct in aws_accounts:
        logging.debug("account val var")
        logging.debug(aws_acct.get("uid"))
        aws_acct_name = aws_acct.get("name")
        acct_uid = aws_acct.get("uid")
        # logging.debug("aws account var")
        # logging.debug(aws_acct)
        logging.debug("aws_acct.cleanup var")
        logging.debug(aws_acct.get("cleanup"))
        if aws_acct.get("cleanup"):
            for x in aws_acct.get("cleanup"):
                if x["provider"] == "cloudwatch":
                    logging.debug("x var")
                    logging.debug(x)
                    logging.debug("x[regex] var")
                    logging.debug(x["regex"])
                    results.append(AWSCloudwatchLogRetention(name=aws_acct_name, acct_uid=acct_uid, log_regex=x["regex"], log_retention_day_length=x['retention_in_days']))

    logging.debug("results var")
    logging.debug(results)
    return results


def set_cloudwatch_retention_period():
    cloudwatch_cleanup_list = get_app_interface_cloudwatch_retention_period()
    logging.debug("cloudwatch_cleanup_list var")
    logging.debug(cloudwatch_cleanup_list)
    for cloudwatch_cleanup_entry in cloudwatch_cleanup_list:
        settings = queries.get_secret_reader_settings()
        accounts = queries.get_aws_accounts(uid=cloudwatch_cleanup_entry.acct_uid)
        awsapi = AWSApi(1, accounts, settings=settings, init_users=False)
        awsapi.set_cloudwatch_log_retention(accounts[0],cloudwatch_cleanup_entry.log_regex)
        # AWSApi.set_cloudwatch_log_retention(cloudwatch_cleanup_entry["log_regex"],cloudwatch_cleanup_entry["acct_uid"])

# def run(dry_run: bool):
#     gqlapi = gql.get_api()

#     valid = True
#     if not validate_no_internal_to_public_peerings(query_data):
#         valid = False
#     if not validate_no_public_to_public_peerings(query_data):
#         valid = False
#     if not validate_no_cidr_overlap(query_data):
#         valid = False

#     if not valid:
#         sys.exit(ExitCodes.ERROR)