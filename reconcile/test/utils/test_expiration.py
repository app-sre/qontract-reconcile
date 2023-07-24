from datetime import (
    datetime,
    timedelta,
)
from typing import Optional

import pytest
from pydantic import BaseModel

from reconcile.utils import expiration

TODAY = datetime.utcnow().date()
YESTERDAY = TODAY - timedelta(days=1)
TOMORROW = TODAY + timedelta(days=1)
NEXT_WEEK = TODAY + timedelta(days=7)
LAST_WEEK = TODAY - timedelta(days=7)


class MyRole(BaseModel):
    just_another_attr: int = 0
    expiration_date: Optional[str]


@pytest.mark.parametrize(
    "in_date, expired",
    [
        (LAST_WEEK.strftime(expiration.DATE_FORMAT), True),
        (YESTERDAY.strftime(expiration.DATE_FORMAT), True),
        (TODAY.strftime(expiration.DATE_FORMAT), True),
        (TOMORROW.strftime(expiration.DATE_FORMAT), False),
        (NEXT_WEEK.strftime(expiration.DATE_FORMAT), False),
    ],
)
def test_date_expired(in_date: str, expired: bool):
    assert expiration.date_expired(in_date) == expired


def test_date_expired_invalid_format():
    with pytest.raises(ValueError):
        expiration.date_expired("garbage")


@pytest.mark.parametrize(
    "roles, expected",
    [
        # valid roles (dict)
        (
            [
                {"expirationDate": "2500-01-01"},
                {"expirationDate": "1990-01-01"},
            ],
            [{"expirationDate": "2500-01-01"}],
        ),
        # valid roles (classes)
        (
            [
                MyRole(expiration_date="2500-01-01"),
                MyRole(expiration_date="1900-01-01"),
            ],
            [MyRole(expiration_date="2500-01-01")],
        ),
        # all roles are expired (dict)
        (
            [
                {"expirationDate": "1990-01-01"},
            ],
            [],
        ),
        # all roles are expired (classes)
        (
            [
                MyRole(expiration_date="1900-01-01"),
            ],
            [],
        ),
        # empty input lists
        ([], []),
        (None, []),
        # no expiration date or None (dict)
        (
            [{"another_key": "foobar"}],
            [{"another_key": "foobar"}],
        ),
        # no expiration date or None (classes)
        (
            [
                MyRole(just_another_attr=1),
                MyRole(expiration_date=None),
            ],
            [MyRole(just_another_attr=1), MyRole(expiration_date=None)],
        ),
    ],
)
def test_filter(roles, expected):
    assert expiration.filter(roles) == expected


@pytest.mark.parametrize(
    "roles",
    [
        # dict
        [{"expirationDate": "garbage"}],
        # class
        [MyRole(expiration_date="garbage")],
    ],
)
def test_filter_invalid_format(roles):
    with pytest.raises(ValueError):
        expiration.filter(roles)
