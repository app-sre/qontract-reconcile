from typing import Any

import pytest
from reconcile.aws_iam_password_reset import get_roles, account_in_roles


@pytest.fixture
def roles() -> list[dict[str, Any]]:
    return [
        {
            "org_username": "foobar",
            "roles": [
                {"name": "test", "aws_groups": None},
                {"name": "test2", "aws_groups": [{"account": {"name": "testaws1"}}]},
            ],
        },
        {"org_username": "barfoo"},
    ]


def test_get_roles(roles: list[dict[str, Any]]):
    r = get_roles(roles, "barfoo")
    assert r and r["org_username"] == "barfoo"
    r = get_roles(roles, "foo")
    assert not r


def test_account_in_roles(roles: list[dict[str, Any]]):
    r = get_roles(roles, "foobar")
    assert r and account_in_roles(r["roles"], "testaws1")
    assert r and not account_in_roles(r["roles"], "a")
