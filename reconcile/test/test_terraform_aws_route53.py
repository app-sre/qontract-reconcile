import pytest
from pytest_mock import MockerFixture

import reconcile.terraform_aws_route53 as integ


@pytest.fixture
def aws_accounts() -> list[dict]:
    return [
        {
            "name": "test-account",
        }
    ]


def test_empty_run(
    mocker: MockerFixture,
    aws_accounts: list[dict],
) -> None:
    mocked_logging = mocker.patch("reconcile.terraform_aws_route53.logging")
    mocked_queries = mocker.patch("reconcile.terraform_aws_route53.queries")
    mocked_queries.get_dns_zones.return_value = []
    mocked_queries.get_aws_accounts.return_value = aws_accounts

    integ.run(False)

    mocked_logging.warning.assert_called_once_with(
        "No participating AWS accounts found, consider disabling this integration, account name: None"
    )
