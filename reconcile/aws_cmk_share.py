import logging
from typing import Any, Iterable, Mapping

from reconcile import queries
from reconcile.aws_ami_share import filter_accounts

from reconcile.utils.aws_api import AWSApi

QONTRACT_INTEGRATION = "aws-cmk-share"
MANAGED_TAG = {"Key": "managed_by_integration", "Value": QONTRACT_INTEGRATION}


def run(dry_run):
    accounts = queries.get_aws_accounts(sharing=True)
    sharing_accounts = filter_accounts(accounts)
    settings = queries.get_app_interface_settings()
    aws_api = AWSApi(1, sharing_accounts, settings=settings, init_users=False)

    for src_account in sharing_accounts:
        sharing = src_account.get("sharing")
        if not sharing:
            continue
        for share in sharing:
            if share["provider"] != "cmk":
                continue
            dst_account = share["account"]

            print(share)
            print(dst_account)
            current_cmks = aws_api.get_cmks_details(src_account)
            print(current_cmks)
