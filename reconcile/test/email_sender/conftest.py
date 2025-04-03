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


@pytest.fixture
def all_service_owners_email(emails: list[AppInterfaceEmailV1]) -> AppInterfaceEmailV1:
    for email in emails:
        if email.name == "all-service-owners":
            return email
    raise ValueError("Email not found")


@pytest.fixture
def all_users_email(emails: list[AppInterfaceEmailV1]) -> AppInterfaceEmailV1:
    for email in emails:
        if email.name == "all-users":
            return email
    raise ValueError("Email not found")


@pytest.fixture
def no_aliases_email(emails: list[AppInterfaceEmailV1]) -> AppInterfaceEmailV1:
    for email in emails:
        if email.name == "no-aliases":
            return email
    raise ValueError("Email not found")


@pytest.fixture
def namespaces_email(emails: list[AppInterfaceEmailV1]) -> AppInterfaceEmailV1:
    for email in emails:
        if email.name == "namespaces":
            return email
    raise ValueError("Email not found")


@pytest.fixture
def clusters_email(emails: list[AppInterfaceEmailV1]) -> AppInterfaceEmailV1:
    for email in emails:
        if email.name == "clusters":
            return email
    raise ValueError("Email not found")
