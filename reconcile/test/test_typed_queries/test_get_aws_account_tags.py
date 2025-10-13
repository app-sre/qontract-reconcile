import pytest

from reconcile.gql_definitions.fragments.aws_organization import (
    AWSAccountV1,
    AWSOrganization,
)
from reconcile.typed_queries.aws_account_tags import get_aws_account_tags


def test_get_aws_account_tags_when_org_is_none() -> None:
    tags = get_aws_account_tags(None)

    assert tags == {}


@pytest.mark.parametrize(
    ("payer_account_tags", "account_tags", "expected_tags"),
    [
        (
            '{"tag1": "value1"}',
            '{"tag2": "value2"}',
            {"tag1": "value1", "tag2": "value2"},
        ),
        (
            "{}",
            '{"tag": "value"}',
            {"tag": "value"},
        ),
        (
            '{"tag": "value"}',
            "{}",
            {"tag": "value"},
        ),
        (
            "{}",
            "{}",
            {},
        ),
        (
            '{"tag": "payer"}',
            '{"tag": "account"}',
            {"tag": "account"},
        ),
    ],
)
def test_get_aws_account_tags(
    payer_account_tags: str,
    account_tags: str,
    expected_tags: dict[str, str],
) -> None:
    organization = AWSOrganization(
        payerAccount=AWSAccountV1(
            organizationAccountTags=payer_account_tags,
        ),
        tags=account_tags,
    )

    tags = get_aws_account_tags(organization)

    assert tags == expected_tags
