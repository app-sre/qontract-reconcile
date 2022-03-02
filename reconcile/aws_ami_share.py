import logging

from reconcile import queries

from reconcile.utils.aws_api import AWSApi

QONTRACT_INTEGRATION = "aws-ami-share"
MANAGED_TAG = {"Key": "managed_by_integration", "Value": QONTRACT_INTEGRATION}


def filter_accounts(accounts):
    sharing_account_names = set()
    for a in accounts:
        sharing = a.get("sharing")
        if sharing:
            sharing_account_names.add(a["name"])
            for s in sharing:
                sharing_account_names.add(s["account"]["name"])

    return [a for a in accounts if a["name"] in sharing_account_names]


def run(dry_run):
    accounts = queries.get_aws_accounts(sharing=True)
    sharing_accounts = filter_accounts(accounts)
    settings = queries.get_app_interface_settings()
    aws_api = AWSApi(1, sharing_accounts, settings=settings)

    for src_account in sharing_accounts:
        sharing = src_account.get("sharing")
        if not sharing:
            continue
        for share in sharing:
            if share["provider"] != "ami":
                continue
            dst_account = share["account"]
            regex = share["regex"]
            src_amis = aws_api.get_amis_details(src_account, src_account, regex)
            dst_amis = aws_api.get_amis_details(dst_account, src_account, regex)

            for src_ami in src_amis:
                src_ami_id = src_ami["image_id"]
                found_dst_amis = [d for d in dst_amis if d["image_id"] == src_ami_id]
                if not found_dst_amis:
                    logging.info(
                        [
                            "share_ami",
                            src_account["name"],
                            dst_account["name"],
                            src_ami_id,
                        ]
                    )
                    if not dry_run:
                        aws_api.share_ami(src_account, dst_account, src_ami_id)
                    # we assume an unshared ami does not have tags
                    found_dst_amis = [{"image_id": src_ami_id, "tags": []}]

                dst_ami = found_dst_amis[0]
                dst_ami_id = dst_ami["image_id"]
                dst_ami_tags = dst_ami["tags"]
                if MANAGED_TAG not in dst_ami_tags:
                    logging.info(
                        ["tag_shared_ami", dst_account["name"], dst_ami_id, MANAGED_TAG]
                    )
                    if not dry_run:
                        aws_api.create_tag(dst_account, dst_ami_id, MANAGED_TAG)
                src_ami_tags = src_ami["tags"]
                for src_tag in src_ami_tags:
                    if src_tag not in dst_ami_tags:
                        logging.info(
                            ["tag_shared_ami", dst_account["name"], dst_ami_id, src_tag]
                        )
                        if not dry_run:
                            aws_api.create_tag(dst_account, dst_ami_id, src_tag)
