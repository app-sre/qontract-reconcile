import logging
import re
from collections.abc import (
    Iterable,
    Mapping,
)
from typing import Any

from reconcile import queries
from reconcile.typed_queries.aws_account_tags import get_aws_account_tags
from reconcile.typed_queries.external_resources import get_settings
from reconcile.utils.aws_api import AWSApi

QONTRACT_INTEGRATION = "aws-ami-share"

MANAGED_TAG = {"managed_by_integration": QONTRACT_INTEGRATION}


def filter_accounts(accounts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    sharing_account_names = set()
    for a in accounts:
        sharing = a.get("sharing")
        if sharing:
            sharing_account_names.add(a["name"])
            sharing_account_names.update(s["account"]["name"] for s in sharing)

    return [a for a in accounts if a["name"] in sharing_account_names]


def get_region(
    share: Mapping[str, Any],
    src_account: Mapping[str, Any],
    dst_account: Mapping[str, Any],
) -> str:
    region = share.get("region") or src_account["resourcesDefaultRegion"]
    if region not in dst_account["supportedDeploymentRegions"]:
        raise ValueError(f"region {region} is not supported in {dst_account['name']}")

    return region


def share_ami(
    dry_run: bool,
    src_account: Mapping[str, Any],
    share: Mapping[str, Any],
    default_tags: dict[str, str],
    aws_api: AWSApi,
) -> None:
    dst_account = share["account"]
    regex = re.compile(share["regex"])
    region = get_region(share, src_account, dst_account)
    src_amis = aws_api.get_amis_details(src_account, src_account, regex, region)
    dst_amis = aws_api.get_amis_details(dst_account, src_account, regex, region)

    for ami_id, src_ami_tags in src_amis.items():
        dst_ami_tags = dst_amis.get(ami_id)
        if dst_ami_tags is None:
            logging.info([
                "share_ami",
                src_account["name"],
                dst_account["name"],
                ami_id,
            ])
            if not dry_run:
                aws_api.share_ami(src_account, dst_account["uid"], ami_id, region)
        dst_account_tags = default_tags | get_aws_account_tags(
            dst_account.get("organization", None)
        )
        desired_tags = src_ami_tags | dst_account_tags | MANAGED_TAG
        current_tags = dst_ami_tags or {}

        if desired_tags != current_tags:
            logging.info([
                "tag_shared_ami",
                dst_account["name"],
                ami_id,
                desired_tags,
            ])
            if not dry_run:
                aws_api.create_tags(dst_account, ami_id, desired_tags)


def run(dry_run: bool) -> None:
    accounts = queries.get_aws_accounts(sharing=True)
    sharing_accounts = filter_accounts(accounts)
    settings = queries.get_app_interface_settings()
    try:
        default_tags = get_settings().default_tags
    except ValueError:
        # no external resources settings found
        default_tags = {}

    with AWSApi(
        1,
        sharing_accounts,
        settings=settings,
        init_users=False,
    ) as aws_api:
        for src_account in sharing_accounts:
            for share in src_account.get("sharing") or []:
                if share["provider"] == "ami":
                    share_ami(
                        dry_run=dry_run,
                        src_account=src_account,
                        share=share,
                        default_tags=default_tags,
                        aws_api=aws_api,
                    )
