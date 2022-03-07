import pytest

import reconcile.aws_ami_share as integ


@pytest.fixture
def accounts():
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


def test_filter_accounts(accounts):
    filtered = [a["name"] for a in integ.filter_accounts(accounts)]
    assert filtered == ["some-account", "shared-account"]


def test_get_region_share_valid():
    share = {"region": "valid"}
    src_account = {"resourcesDefaultRegion": "doesnt-matter"}
    dst_account = {"supportedDeploymentRegions": ["valid"]}
    result = integ.get_region(share, src_account, dst_account)
    assert result == "valid"


def test_get_region_default_no_share():
    share = {"region": None}
    src_account = {"resourcesDefaultRegion": "valid"}
    dst_account = {"supportedDeploymentRegions": ["valid"]}
    result = integ.get_region(share, src_account, dst_account)
    assert result == "valid"


def test_get_region_share_invalid():
    share = {"region": "invalid"}
    src_account = {"resourcesDefaultRegion": "doesnt-matter"}
    dst_account = {"name": "really", "supportedDeploymentRegions": ["valid"]}
    with pytest.raises(ValueError):
        integ.get_region(share, src_account, dst_account)
