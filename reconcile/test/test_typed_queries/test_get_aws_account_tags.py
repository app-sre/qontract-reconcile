from collections.abc import Mapping

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
    ("organization", "expected_tags"),
    [
        # trivial cases
        (None, {}),
        ({}, {}),
        # GQL objects
        (
            AWSOrganization(
                payerAccount=AWSAccountV1(organizationAccountTags='{"tag1": "value1"}'),
                tags='{"tag2": "value2"}',
            ),
            {"tag1": "value1", "tag2": "value2"},
        ),
        (
            AWSOrganization(
                payerAccount=AWSAccountV1(organizationAccountTags="{}"),
                tags='{"tag": "value"}',
            ),
            {"tag": "value"},
        ),
        (
            AWSOrganization(
                payerAccount=AWSAccountV1(organizationAccountTags='{"tag": "value"}'),
                tags="{}",
            ),
            {"tag": "value"},
        ),
        (
            AWSOrganization(
                payerAccount=AWSAccountV1(organizationAccountTags="{}"), tags="{}"
            ),
            {},
        ),
        (
            AWSOrganization(
                payerAccount=AWSAccountV1(organizationAccountTags='{"tag": "payer"}'),
                tags='{"tag": "account"}',
            ),
            {"tag": "account"},
        ),
        # via dict and json objects
        (
            {
                "payerAccount": {
                    "organizationAccountTags": {"tag1": "value1"},
                },
                "tags": {"tag2": "value2"},
            },
            {"tag1": "value1", "tag2": "value2"},
        ),
        (
            {
                "payerAccount": {
                    "organizationAccountTags": {},
                },
                "tags": {"tag": "value"},
            },
            {"tag": "value"},
        ),
        (
            {
                "payerAccount": {
                    "organizationAccountTags": {"tag": "value"},
                },
                "tags": {},
            },
            {"tag": "value"},
        ),
        (
            {"payerAccount": {"organizationAccountTags": {}}, "tags": {}},
            {},
        ),
        (
            {
                "payerAccount": {
                    "organizationAccountTags": {"tag": "payer"},
                },
                "tags": {"tag": "account"},
            },
            {"tag": "account"},
        ),
        # via dict and json strings
        (
            {
                "payerAccount": {
                    "organizationAccountTags": '{"tag1": "value1"}',
                },
                "tags": '{"tag2": "value2"}',
            },
            {"tag1": "value1", "tag2": "value2"},
        ),
        (
            {
                "payerAccount": {
                    "organizationAccountTags": "{}",
                },
                "tags": '{"tag": "value"}',
            },
            {"tag": "value"},
        ),
        (
            {
                "payerAccount": {
                    "organizationAccountTags": '{"tag": "value"}',
                },
                "tags": "{}",
            },
            {"tag": "value"},
        ),
        (
            {"payerAccount": {"organizationAccountTags": "{}"}, "tags": "{}"},
            {},
        ),
        (
            {
                "payerAccount": {
                    "organizationAccountTags": '{"tag": "payer"}',
                },
                "tags": '{"tag": "account"}',
            },
            {"tag": "account"},
        ),
    ],
)
def test_get_aws_account_tags(
    organization: AWSOrganization | Mapping,
    expected_tags: dict[str, str],
) -> None:
    tags = get_aws_account_tags(organization)

    assert tags == expected_tags
