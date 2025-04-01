from collections.abc import Callable, Mapping
from typing import Any

import pytest

from reconcile.email_sender import get_emails
from reconcile.gql_definitions.email_sender.emails import AppInterfaceEmailV1
from reconcile.test.fixtures import Fixtures


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("email_sender")


@pytest.fixture
def emails_query(
    data_factory: Callable[
        [type[AppInterfaceEmailV1], Mapping[str, Any]], Mapping[str, Any]
    ],
    fx: Fixtures,
) -> Callable:
    def q(*args: Any, **kwargs: Any) -> dict:
        return {
            "emails": [
                data_factory(AppInterfaceEmailV1, item)
                for item in fx.get_anymarkup("emails.yml")["emails"]
            ]
        }

    return q


@pytest.fixture
def emails(emails_query: Callable) -> list[AppInterfaceEmailV1]:
    return get_emails(emails_query)
