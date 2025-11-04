import re
from collections.abc import Iterable
from unittest.mock import call, create_autospec

import pytest

import reconcile.aws_ami_share as integ
from reconcile.utils.aws_api import AWSApi


@pytest.fixture
def accounts() -> list[dict]:
    return [
        {
            "name": "some-account",
            "automationToken": {
                "path": "path",
            },
            "resourcesDefaultRegion": "default-region",
            "sharing": [
                {
                    "provider": "ami",
                    "account": {
                        "name": "shared-account",
                        "uid": 123,
                    },
                }
            ],
        },
        {
            "name": "some-account-too",
            "automationToken": {
                "path": "path",
            },
            "resourcesDefaultRegion": "default-region",
        },
        {
            "name": "shared-account",
            "automationToken": {
                "path": "path",
            },
            "resourcesDefaultRegion": "default-region",
        },
    ]


def test_filter_accounts(accounts: Iterable[dict]) -> None:
    filtered = [a["name"] for a in integ.filter_accounts(accounts)]
    assert filtered == ["some-account", "shared-account"]


def test_get_region_share_valid() -> None:
    share = {"region": "valid"}
    src_account = {"resourcesDefaultRegion": "doesnt-matter"}
    dst_account = {"supportedDeploymentRegions": ["valid"]}
    result = integ.get_region(share, src_account, dst_account)
    assert result == "valid"


def test_get_region_default_no_share() -> None:
    share = {"region": None}
    src_account = {"resourcesDefaultRegion": "valid"}
    dst_account = {"supportedDeploymentRegions": ["valid"]}
    result = integ.get_region(share, src_account, dst_account)
    assert result == "valid"


def test_get_region_share_invalid() -> None:
    share = {"region": "invalid"}
    src_account = {"resourcesDefaultRegion": "doesnt-matter"}
    dst_account = {"name": "really", "supportedDeploymentRegions": ["valid"]}
    with pytest.raises(ValueError):
        integ.get_region(share, src_account, dst_account)


def test_share_ami() -> None:
    aws_api = create_autospec(AWSApi)
    aws_api.get_amis_details.side_effect = [
        {"ami-1": {"k": "v"}},
        {},
    ]
    src_account = {
        "name": "src-account",
        "resourcesDefaultRegion": "us-east-1",
    }
    dst_account = {
        "name": "dst-account",
        "uid": "dst-account-uid",
        "supportedDeploymentRegions": "us-east-1",
        "organization": {
            "payerAccount": {"organizationAccountTags": '{"payer_key": "payer_value"}'},
            "tags": '{"account_key": "account_value"}',
        },
    }

    integ.share_ami(
        dry_run=False,
        src_account=src_account,
        share={
            "account": dst_account,
            "regex": ".*",
        },
        default_tags={"default_key": "default_value"},
        aws_api=aws_api,
    )

    assert aws_api.get_amis_details.call_count == 2
    expected_regex = re.compile(r".*")
    aws_api.get_amis_details.assert_has_calls([
        call(
            src_account,
            src_account,
            expected_regex,
            "us-east-1",
        ),
        call(
            dst_account,
            src_account,
            expected_regex,
            "us-east-1",
        ),
    ])
    aws_api.share_ami.assert_called_once_with(
        src_account,
        "dst-account-uid",
        "ami-1",
        "us-east-1",
    )
    aws_api.create_tags.assert_called_once_with(
        dst_account,
        "ami-1",
        {
            "k": "v",
            "default_key": "default_value",
            "account_key": "account_value",
            "payer_key": "payer_value",
            "managed_by_integration": "aws-ami-share",
        },
    )
