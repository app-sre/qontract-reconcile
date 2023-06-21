import logging
from collections.abc import (
    Callable,
)

from typing import (
    TYPE_CHECKING,
    Optional,
)

from pydantic import (
    BaseModel,
)

from reconcile import queries

from reconcile.queries import get_aws_accounts

from reconcile.utils.aws_api import AWSApi

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


def get_app_interface_cloudwatch_retention_period() -> None:
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
                    results.append(
                        AWSCloudwatchLogRetention(
                            name=aws_acct_name,
                            acct_uid=acct_uid,
                            log_regex=x["regex"],
                            log_retention_day_length=x["retention_in_days"],
                        )
                    )

    logging.debug("results var")
    logging.debug(results)
    return results


def parse_log_retention_date(retention_period) -> int:
    if retention_period[-1] == "d":
        return int(retention_period[:-1])
    raise ValueError(
        "Invalid retention period format. Expected format is <numeric value>d"
    )


def run(dry_run: bool, thread_pool_size: int, defer: Optional[Callable] = None) -> None:
    cloudwatch_cleanup_list = get_app_interface_cloudwatch_retention_period()
    logging.debug("cloudwatch_cleanup_list var")
    logging.debug(cloudwatch_cleanup_list)
    for cloudwatch_cleanup_entry in cloudwatch_cleanup_list:
        settings = queries.get_secret_reader_settings()
        accounts = queries.get_aws_accounts(uid=cloudwatch_cleanup_entry.acct_uid)
        awsapi = AWSApi(1, accounts, settings=settings, init_users=False)
        logging.debug("cloudwatch_cleanup_entry.log_retention_day_length var")
        logging.debug(cloudwatch_cleanup_entry.log_retention_day_length)
        transformed_retention_day_length = parse_log_retention_date(
            cloudwatch_cleanup_entry.log_retention_day_length
        )
        logging.debug("transformed_retention_day_length var")
        logging.debug(transformed_retention_day_length)
        awsapi.set_cloudwatch_log_retention(
            accounts[0],
            cloudwatch_cleanup_entry.log_regex,
            transformed_retention_day_length,
        )
